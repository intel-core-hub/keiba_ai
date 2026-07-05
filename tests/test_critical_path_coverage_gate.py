from __future__ import annotations

import socket
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.decision_engine import Decision, DecisionEngine
from core.circuit_breaker import SharedCircuitBreaker
from core.execution.bet_executor import (
    BetExecutor,
    _parse_bool,
    _read_safe_mode_from_settings,
    _read_shadow_mode_from_settings,
)
from scripts.stage4_readiness_gate import (
    GateResult,
    _coverage_file_entry,
    blocking_summary,
    classify_failures,
    event_payload,
    event_timestamp,
    failure_layer,
    numeric,
    stage4_verdict,
    validate_critical_path_coverage,
    validate_latency,
    validate_shadow_coverage,
    validate_shadow_safety,
)


class _Predictor:
    trained = True
    model_hash = "model-hash"

    def __init__(self, probability: float = 0.82):
        self.probability = probability

    def predict(self, race_id, selection, features, odds=None):
        return self.probability


class _Calibrator:
    def calibrate(self, value):
        return float(value)


class _BetSizer:
    def __init__(self, stake: int = 500, *, fail: bool = False):
        self.stake = stake
        self.fail = fail

    def calculate_bet(self, **kwargs):
        if self.fail:
            raise RuntimeError("risk sizing failed")
        return self.stake


class _RiskManager:
    bankroll = 100_000.0

    def __init__(self, *, can_bet: bool = True, multiplier: float = 1.0, max_bet: int = 1_000):
        self._can_bet = can_bet
        self._multiplier = multiplier
        self._max_bet = max_bet
        self.registered = []
        self.updated_after = []
        self.reset_called = False
        self.fail_update_uncertainty = False
        self.fail_update_calibration = False
        self.fail_adjust = False

    def status(self):
        return {
            "bankroll": self.bankroll,
            "drawdown": 0.0,
            "risk_multiplier": self._multiplier,
            "lose_streak": 0,
            "win_streak": 0,
            "race_risk_used": 0.0,
            "defensive_mode": False,
        }

    def can_bet(self):
        return self._can_bet

    def risk_multiplier(self):
        return self._multiplier

    def max_bet_size(self):
        return self._max_bet

    def drawdown(self):
        return 0.0

    def reset_race_risk(self):
        self.reset_called = True

    def register_bet(self, amount):
        self.registered.append(amount)

    def update_after_race(self, profit):
        self.updated_after.append(profit)
        self.bankroll += profit

    def update_uncertainty_state(self, **kwargs):
        if self.fail_update_uncertainty:
            raise RuntimeError("uncertainty unavailable")

    def update_calibration_state(self, state):
        if self.fail_update_calibration:
            raise RuntimeError("calibration unavailable")

    def adjust_bet_sizer(self, bet_sizer):
        if self.fail_adjust:
            raise RuntimeError("adjust unavailable")


class _BrokenRiskManager(_RiskManager):
    def status(self):
        raise RuntimeError("status failed")

    def can_bet(self):
        raise RuntimeError("can_bet failed")

    def risk_multiplier(self):
        raise RuntimeError("risk_multiplier failed")

    def max_bet_size(self):
        raise RuntimeError("max_bet failed")


class _EdgeCalculator:
    def __init__(self, *, bettable: bool = True, edge: float = 0.18, expected_value: float = 0.55):
        self.bettable = bettable
        self.edge = edge
        self.expected_value = expected_value

    def calculate_edge(self, **kwargs):
        odds = float(kwargs["odds"])
        return {
            "market_prob": 1.0 / odds,
            "edge": self.edge,
            "expected_value": self.expected_value,
        }

    def is_bettable(self, edge, expected_value):
        return self.bettable


class _EdgeQuality:
    def __init__(self, quality: float = 0.8, min_quality: float = 0.5):
        self.quality = quality
        self.min_quality = min_quality

    def evaluate(self, **kwargs):
        return self.quality


class _Logger:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.decisions = []
        self.outcomes = []

    def log_decision(self, **kwargs):
        if self.fail:
            raise RuntimeError("logger failed")
        self.decisions.append(kwargs)

    def log_outcome(self, **kwargs):
        self.outcomes.append(kwargs)


class _Telemetry:
    def __init__(self):
        self.metrics = []

    def record_metric(self, name, value):
        self.metrics.append((name, value))


class _NoBetFilter:
    def __init__(self, skip: bool = False, reason: str = "manual_stop"):
        self.skip = skip
        self.reason = reason

    def should_skip(self, **kwargs):
        return self.skip, self.reason


class _UncertaintyFilter:
    def __init__(self, *, skip: bool = False, fail: bool = False, reason: str = "UNCERTAINTY_SKIP"):
        self.skip = skip
        self.fail = fail
        self.reason = reason
        self.samples = []

    def add_sample(self, value):
        if self.fail:
            raise RuntimeError("filter down")
        self.samples.append(value)

    def should_skip(self, value):
        if self.fail:
            raise RuntimeError("filter down")
        return self.skip, self.reason


def _engine(
    *,
    predictor: _Predictor | None = None,
    risk_manager: _RiskManager | None = None,
    bet_sizer: _BetSizer | None = None,
    logger: _Logger | None = None,
    telemetry: _Telemetry | None = None,
    edge_calculator: _EdgeCalculator | None = None,
    edge_quality: _EdgeQuality | None = None,
    no_bet_filter: _NoBetFilter | None = None,
    max_uncertainty: float = 1.0,
) -> DecisionEngine:
    engine = DecisionEngine(
        predictor=predictor or _Predictor(),
        bet_sizer=bet_sizer or _BetSizer(),
        risk_manager=risk_manager or _RiskManager(),
        no_bet_filter=no_bet_filter,
        decision_logger=logger,
        telemetry=telemetry,
        edge_calculator=edge_calculator or _EdgeCalculator(),
        edge_quality_filter=edge_quality or _EdgeQuality(),
        calibrator=_Calibrator(),
        max_uncertainty=max_uncertainty,
    )
    engine.allow_fallback_betting = True
    engine.uncertainty_filter = _UncertaintyFilter()
    return engine


def _candidate(**overrides):
    data = {
        "selection": "H1",
        "odds": 5.0,
        "features": {"speed": 1.0},
        "regime": "NORMAL",
        "odds_snapshot_hash": "odds-hash",
        "feature_snapshot_hash": "feature-hash",
    }
    data.update(overrides)
    return data


def _decision(**overrides) -> Decision:
    decision = Decision(
        race_id="R1",
        selection="H1",
        probability=0.2,
        calibrated_probability=0.18,
        market_probability=0.1,
        odds=10.0,
        edge=0.05,
        expected_value=0.8,
        uncertainty_score=0.1,
        edge_quality=0.7,
        bet_size=500,
        risk_limits_hash="risk-hash",
        risk_clamp_reason="risk_clamp_allowed",
        risk_clamp_allowed=True,
        policy_hash="policy-hash",
        model_hash="model-hash",
        odds_snapshot_hash="odds-hash",
        feature_snapshot_hash="feature-hash",
    )
    for key, value in overrides.items():
        setattr(decision, key, value)
    return decision


def test_decision_engine_helpers_cover_fail_closed_edges():
    predictor = _Predictor()
    predictor.trained = False
    engine = _engine(predictor=predictor)
    engine.allow_fallback_betting = False
    assert engine._sanity_guard_reason(odds=2.0, calibrated_probability=0.5, market_probability=0.5) == "MODEL_FALLBACK_NO_BET"

    predictor.trained = True
    engine.allow_fallback_betting = True
    assert engine._sanity_guard_reason(odds=60.0, calibrated_probability=0.2, market_probability=0.1) == "LONGSHOT_ODDS_LIMIT"
    assert engine._sanity_guard_reason(odds=35.0, calibrated_probability=0.16, market_probability=0.03) == "LONGSHOT_PROB_GAP"
    assert engine._sanity_guard_reason(odds=25.0, calibrated_probability=0.31, market_probability=0.04) == "LONGSHOT_MARKET_PROB_RATIO"
    assert engine._sanity_guard_reason(odds=25.0, calibrated_probability=0.31, market_probability=0.0) is None
    assert engine._sanity_guard_reason(odds=8.0, calibrated_probability=0.16, market_probability=0.12) is None

    engine.set_calibration_state(None)
    engine.set_uncertainty_profile()
    engine.set_uncertainty_profile({"center": 0.4, "width": 0.2}, max_uncertainty=0.7)
    assert engine.uncertainty_profile["center"] == 0.4
    assert engine.max_uncertainty == 0.7

    for state, expected in (
        ({"mean_brier": 0.25, "mean_ece": 0.08, "mean_reliability": 0.89}, 0.55 * 0.60 * 0.70),
        ({"brier": 0.21, "ece": 0.05, "reliability": 0.93}, 0.75 * 0.80 * 0.85),
        ({"brier": 0.15, "ece": 0.02, "reliability": 0.98}, 1.0),
    ):
        engine.calibration_state = {}
        engine.set_calibration_state(state)
        assert engine._calibration_multiplier() == pytest.approx(expected)

    no_risk = DecisionEngine(
        predictor=_Predictor(),
        bet_sizer=_BetSizer(),
        risk_manager=None,
        calibrator=_Calibrator(),
    )
    assert no_risk._risk_provider_snapshot()["can_bet"] is False
    broken = _engine(risk_manager=_BrokenRiskManager())._risk_provider_snapshot()
    assert broken == {"can_bet": False, "risk_multiplier": 0.0, "max_bet_size": 0.0, "status": {}}


def test_decision_engine_success_logs_telemetry_and_outcomes():
    logger = _Logger()
    telemetry = _Telemetry()
    risk = _RiskManager(max_bet=300)
    engine = _engine(risk_manager=risk, logger=logger, telemetry=telemetry)

    decision = engine.evaluate_candidate("R1", _candidate())

    assert decision is not None
    assert decision.bet_size == 300
    assert decision.risk_clamp_allowed is True
    assert risk.registered == [300.0]
    assert logger.decisions[-1]["decision"] == "BET"
    assert {name for name, _value in telemetry.metrics} >= {"pred_prob", "bet_size"}

    assert engine.update_result(decision, hit=True) == pytest.approx(1200.0)
    assert engine.update_result(replace(decision, bet_size=200), hit=False) == -200
    assert logger.outcomes[-1]["hit"] is False
    assert any(name == "profit" for name, _value in telemetry.metrics)


@pytest.mark.parametrize(
    ("engine_kwargs", "candidate_overrides", "expected_skip"),
    [
        ({}, {"odds": None}, None),
        ({"edge_quality": _EdgeQuality(quality=0.2, min_quality=0.5)}, {}, "LOW_EDGE_QUALITY"),
        ({"predictor": _Predictor(probability=0.5), "max_uncertainty": 0.1}, {}, "HIGH_UNCERTAINTY"),
        ({"edge_calculator": _EdgeCalculator(bettable=False)}, {}, "INSUFFICIENT_EDGE"),
        ({"no_bet_filter": _NoBetFilter(skip=True, reason="session_expired")}, {}, "session_expired"),
        ({"bet_sizer": _BetSizer(fail=True)}, {}, "risk_limits_invalid"),
        ({"risk_manager": _RiskManager(can_bet=False)}, {}, "risk_limits_invalid"),
    ],
)
def test_decision_engine_skip_paths(engine_kwargs, candidate_overrides, expected_skip):
    logger = _Logger()
    engine = _engine(logger=logger, **engine_kwargs)

    decision = engine.evaluate_candidate("R1", _candidate(**candidate_overrides))

    assert decision is None
    if expected_skip is not None:
        assert logger.decisions[-1]["skip_reason"] == expected_skip


def test_decision_engine_uncertainty_filter_skip_and_failure_paths():
    logger = _Logger()
    skip_engine = _engine(logger=logger)
    skip_engine.uncertainty_filter = _UncertaintyFilter(skip=True, reason="rolling_uncertainty")

    assert skip_engine.evaluate_candidate("R1", _candidate()) is None
    assert logger.decisions[-1]["skip_reason"] == "rolling_uncertainty"

    risk = _RiskManager()
    risk.fail_update_uncertainty = True
    risk.fail_update_calibration = True
    risk.fail_adjust = True
    continue_engine = _engine(risk_manager=risk)
    continue_engine.uncertainty_filter = _UncertaintyFilter(fail=True)

    assert continue_engine.evaluate_candidate("R1", _candidate()) is not None


def test_decision_engine_decide_race_filters_correlated_horses():
    engine = _engine()
    engine.max_per_race = 2

    decisions = engine.decide_race(
        "R1",
        [
            _candidate(selection="H1-H2", odds=4.0),
            _candidate(selection="H2-H3", odds=5.0),
            _candidate(selection="H4", odds=6.0),
        ],
    )

    assert engine.risk_manager.reset_called is True
    assert [decision.selection for decision in decisions] == ["H1-H2", "H4"]


def _executor(tmp_path: Path, **overrides) -> BetExecutor:
    decision_log_path = overrides.pop("decision_log_path", tmp_path / "decisions.jsonl")
    csv_report_path = overrides.pop("csv_report_path", tmp_path / "bets.csv")
    model_path = overrides.pop("model_path", tmp_path / "model.pkl")
    calibrator_state_path = overrides.pop("calibrator_state_path", tmp_path / "calibration.pkl")
    return BetExecutor(
        risk_manager=overrides.pop("risk_manager", _RiskManager()),
        decision_log_path=str(decision_log_path),
        csv_report_path=str(csv_report_path),
        safe_mode=overrides.pop("safe_mode", True),
        shadow_mode=overrides.pop("shadow_mode", True),
        model_path=str(model_path),
        calibrator_state_path=str(calibrator_state_path),
        **overrides,
    )


def test_bet_executor_settings_and_runtime_file_helpers(tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        """
        # comment
        safe mode: off
        shadow_mode: "yes"
        ignored
        """,
        encoding="utf-8",
    )
    assert _parse_bool(None, default=False) is False
    assert _parse_bool(True) is True
    assert _parse_bool("on") is True
    assert _parse_bool("off") is False
    assert _parse_bool("not-bool", default=True) is True
    assert _read_safe_mode_from_settings(settings, default=True) is False
    assert _read_shadow_mode_from_settings(settings, default=False) is True
    assert _read_safe_mode_from_settings(tmp_path / "missing.yaml", default=True) is True
    assert _read_shadow_mode_from_settings(tmp_path, default=True) is True

    model = tmp_path / "model.pkl"
    model.write_bytes(b"model")
    executor = _executor(tmp_path, model_path=str(model))
    assert executor._file_sha256(model, missing="missing") != "missing"
    assert executor._file_mtime_iso(model, missing="missing") != "missing"
    assert executor._file_sha256(tmp_path / "empty.pkl", missing="missing") == "missing"
    assert executor._file_mtime_iso(tmp_path / "empty.pkl", missing="missing") == "missing"


def test_bet_executor_csv_initialization_migrates_existing_rows(tmp_path):
    csv_path = tmp_path / "bets.csv"
    csv_path.write_text("race_id,selection\nR1,H1\n", encoding="utf-8")

    executor = _executor(tmp_path, csv_report_path=str(csv_path))

    first_line = csv_path.read_text(encoding="utf-8").splitlines()[0]
    assert "risk_limits_hash" in first_line
    assert executor.log_path == csv_path


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (None, None),
        (lambda: (True, "HALT"), "HALT"),
        (lambda: (False, "OK"), None),
        (lambda: True, "EMERGENCY_SOURCE"),
        (lambda: (_ for _ in ()).throw(RuntimeError("boom")), "EMERGENCY_SOURCE_ERROR"),
        (SimpleNamespace(destroyed=True, last_reason="DESTROYED_NOW"), "DESTROYED_NOW"),
        (SimpleNamespace(emergency_mode=True), "EMERGENCY_MODE"),
        (SimpleNamespace(shutdown=True), "SHUTDOWN"),
        (SimpleNamespace(status=lambda: {"destroyed": True, "last_reason": "STATUS_DESTROYED"}), "STATUS_DESTROYED"),
        (SimpleNamespace(status=lambda: {"shutdown": True, "reason": "STATUS_SHUTDOWN"}), "STATUS_SHUTDOWN"),
        (SimpleNamespace(status=lambda: {"emergency_mode": True, "reason": "STATUS_EMERGENCY"}), "STATUS_EMERGENCY"),
        (SimpleNamespace(status=lambda: (_ for _ in ()).throw(RuntimeError("status"))), None),
        (SimpleNamespace(should_shutdown=lambda: True), "SHOULD_SHUTDOWN"),
        (SimpleNamespace(should_shutdown=lambda: (_ for _ in ()).throw(RuntimeError("status"))), None),
    ],
)
def test_bet_executor_emergency_source_branches(tmp_path, source, expected):
    executor = _executor(tmp_path)
    assert executor._should_block_from_source(source) == expected


def test_bet_executor_modes_blocking_and_failure_registration(tmp_path):
    breaker = SharedCircuitBreaker(failure_threshold=1, recovery_timeout=60)
    executor = _executor(tmp_path, circuit_breaker=breaker, emergency_sources=[lambda: (False, "")])
    assert executor.is_blocked() is False
    assert executor._normalize_stake(600) == 100
    assert executor._execution_mode_label() == "SHADOW_MODE"

    executor.resume_from_emergency()
    executor.emergency_shutdown("manual", source="test", pause_only=False)
    assert executor.is_blocked() is True
    assert executor.execute_bet(_decision())["state"] == "STANDBY"
    executor.resume_from_emergency()

    breaker.force_open("TEST_OPEN")
    assert executor.execute_bet(_decision())["reason"] == "TEST_OPEN"

    live = _executor(tmp_path / "live", safe_mode=False, shadow_mode=False)
    assert live._normalize_stake(600) == 600
    assert live._normalize_stake(-10) == 0
    assert live._execution_mode_label() == "LIVE_MODE"

    safe = _executor(tmp_path / "safe", safe_mode=True, shadow_mode=False)
    assert safe._execution_mode_label() == "SAFE_MODE"


def test_bet_executor_real_vote_and_api_error_paths(tmp_path):
    base = _executor(tmp_path, shadow_mode=False, safe_mode=False)
    blocked = base._execute_real_vote({"risk_clamp_allowed": False})
    assert blocked["status"] == "blocked"
    assert base._execute_real_vote({"risk_clamp_allowed": True, "race_id": "R1"})["status"] == "dry_run"

    callable_executor = _executor(
        tmp_path / "callable",
        shadow_mode=False,
        safe_mode=False,
        api_client=lambda info: {"status": "submitted", "submitted": True, "provider": "callable"},
    )
    assert callable_executor._execute_real_vote({"risk_clamp_allowed": True})["submitted"] is True

    method_client = SimpleNamespace(place_bet=lambda info: {"status": "accepted", "submitted": True})
    method_executor = _executor(tmp_path / "method", shadow_mode=False, safe_mode=False, api_client=method_client)
    assert method_executor._execute_real_vote({"risk_clamp_allowed": True})["status"] == "accepted"

    unsupported = _executor(tmp_path / "unsupported", shadow_mode=False, safe_mode=False, api_client=object())
    with pytest.raises(NotImplementedError):
        unsupported._execute_real_vote({"risk_clamp_allowed": True})

    shadow = _executor(
        tmp_path / "shadow",
        shadow_mode=True,
        odds_confirmer=lambda info: (_ for _ in ()).throw(RuntimeError("odds source")),
    )
    assert shadow._execute_real_vote({"risk_clamp_allowed": True, "predicted_odds": 4.5})["confirmed_odds"] == 4.5

    with pytest.raises(TimeoutError):
        base._call_with_timeout(time.sleep, 0.05, timeout_seconds=0.001)

    class _ResponseError(Exception):
        def __init__(self, status_code):
            self.response = SimpleNamespace(status_code=status_code)
            super().__init__(f"response {status_code}")

    class NetworkError(Exception):
        pass

    assert base._classify_api_error(TimeoutError("late")) == "timeout"
    assert base._classify_api_error(socket.timeout("late")) == "timeout"
    assert base._classify_api_error(_ResponseError(401)) == "session_expired"
    assert base._classify_api_error(_ResponseError(403)) == "ip_blocked"
    assert base._classify_api_error(RuntimeError("ip block detected")) == "ip_blocked"
    assert base._classify_api_error(RuntimeError("unauthorized session")) == "session_expired"
    assert base._classify_api_error(RuntimeError("forbidden")) == "ip_blocked"
    assert base._classify_api_error(NetworkError("network down")) == "network"
    assert base._classify_api_error(ValueError("other")) == "unexpected"

    timeout_executor = _executor(tmp_path / "timeout", max_consecutive_timeouts=1)
    assert timeout_executor._register_failure("timeout", TimeoutError("late"))["reason"] == "retry_budget_exceeded"

    auth_executor = _executor(tmp_path / "auth", max_consecutive_auth_errors=1)
    assert auth_executor._register_failure("ip_blocked", RuntimeError("blocked"))["reason"] == "ip_blocked"

    reset_executor = _executor(tmp_path / "reset")
    assert reset_executor._register_failure("unexpected", RuntimeError("other")) is None


def test_bet_executor_execute_accept_reject_and_settle_paths(tmp_path):
    accepted = _executor(
        tmp_path / "accepted",
        shadow_mode=False,
        safe_mode=False,
        api_client=lambda info: {"status": "accepted", "submitted": True, "confirmed_odds": "bad"},
    )
    result = accepted.execute_bet(_decision(odds_snapshot_ts="2026-01-01T00:00:00Z"))
    assert result["blocked"] is False
    assert result["row"]["api_status"] == "accepted"
    assert result["row"]["mode"] == "LIVE_MODE"
    assert result["row"]["confirmed_odds"] == result["row"]["predicted_odds"]

    rejected = _executor(
        tmp_path / "rejected",
        shadow_mode=False,
        safe_mode=False,
        api_client=lambda info: (_ for _ in ()).throw(TimeoutError("timed out")),
        max_consecutive_timeouts=2,
    )
    error = rejected.execute_bet(_decision())
    assert error["api_result"]["status"] == "error"
    assert error["row"]["api_error"]

    callback_payloads = []
    settling = _executor(tmp_path / "settling", on_settle=callback_payloads.append)
    settled = settling.update_result(_decision(), hit=1, profit=900.0)
    assert settled["profit"] == 900.0
    assert callback_payloads[-1]["profit"] == 900.0


def test_stage4_coverage_gate_and_summary_branches(tmp_path):
    evidence, metric = classify_failures(
        {
            "replay": {"reason": "missing_replay_evidence"},
            "critical_path_coverage": {"evidence_present": False},
            "latency": {"failures": ["p99 >= 200ms"]},
        },
        ["replay", "critical_path_coverage", "latency", "unknown"],
    )
    assert evidence == ["replay", "critical_path_coverage", "unknown"]
    assert metric == ["latency"]
    assert failure_layer("replay", {"reason": "replay_mismatch_count"}) == "metric"
    assert stage4_verdict({"passed": True}, {"passed": True}) == "PASS"
    assert stage4_verdict({"passed": False}, {"passed": True}) == "EVIDENCE_BLOCKED"
    assert stage4_verdict({"passed": True}, {"passed": False}) == "METRIC_FAILED"
    assert stage4_verdict({"passed": False}, {"passed": False}) == "EVIDENCE_BLOCKED_AND_METRIC_FAILED"

    report = GateResult()
    report.fail("required_artifacts", {"missing": ["decision_log"]})
    as_dict = report.to_dict()
    assert as_dict["evidence_gate"]["failures"] == ["required_artifacts"]
    assert "required_artifacts.decision_log missing" in as_dict["blocking_reasons"]

    summary = blocking_summary(
        {
            "market_dependency": {
                "missing_variants": ["closing_odds"],
                "unavailable_variants": ["early_odds_only"],
                "missing_odds_buckets": ["LONGSHOT"],
                "invalid_odds_buckets": [{"odds_regime": "FAVORITE_HEAVY"}],
                "missing_files": [str(tmp_path / "variant_summary.csv")],
                "missing_perturbations": ["odds_up_10pct"],
                "market_copy_score": None,
            },
            "payload_hashes": {"missing_payload_hash": 1},
            "governance_lint": {
                "runtime_import_violations": ["x"],
                "critical_path_violations": ["y"],
                "duplicate_implementations": {"z": []},
            },
        },
        ["market_dependency", "payload_hashes", "governance_lint"],
    )
    assert "market_dependency.closing_odds missing" in summary["blocking_reasons"]
    assert "audit_hash_fields.missing_payload_hash > 0" in summary["blocking_reasons"]
    assert "governance_lint.duplicate_implementations > 0" in summary["blocking_reasons"]

    assert event_timestamp({"payload": {"timestamp": "2026-01-01T00:00:00Z"}}).year == 2026
    assert event_timestamp({"timestamp": "not-a-date"}) is None
    assert event_payload({"payload": "not-dict", "x": 1})["x"] == 1
    assert numeric("bad") is None
    assert validate_shadow_coverage([])["reason"] == "no_event_timestamps"
    unsafe = validate_shadow_safety(
        [
            {"event_type": "BetAccepted", "event_id": "E1", "payload": {}},
            {"event_type": "BetSubmitted", "event_id": "E2", "payload": {"execution_status": "LIVE", "shadow_mode": False}},
        ]
    )
    assert unsafe["unsafe_execution_count"] == 2

    latency = tmp_path / "latency.json"
    latency.write_text('{"p50": null, "p95": 100, "p99": 400, "p999": 300, "timeout_rate": 1, "baseline_p99": 100}', encoding="utf-8")
    latency_result = validate_latency(latency)
    assert "p50 missing" in latency_result["failures"]
    assert "latency_regression_rate >= 30%" in latency_result["failures"]

    assert validate_critical_path_coverage(None)["evidence_present"] is False
    missing = validate_critical_path_coverage(tmp_path / "missing.json")
    assert missing["reason"] == "coverage_json_missing"
    assert _coverage_file_entry({"x\\core\\betting\\decision_engine.py": {"summary": {}}}, "core/betting/decision_engine.py") is not None

    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        '{"files":{"core/betting/decision_engine.py":{"summary":{"num_branches":0,"covered_branches":0,"percent_covered":91}}}}',
        encoding="utf-8",
    )
    coverage_result = validate_critical_path_coverage(coverage)
    assert coverage_result["passed"] is False
    assert "core/betting/risk_clamp.py" in coverage_result["missing_critical_files"]
