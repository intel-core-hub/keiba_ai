import inspect
import asyncio
import csv
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ipat_adapter import MockIPATClient, RealIPATClient, build_from_env
from core.bet_sizer import BetConfig
from core.circuit_breaker import SharedCircuitBreaker
from core.betting.decision_engine import Decision
from core.execution.bet_executor import BetExecutor
from core.execution.calibration_refit import CalibrationRefitJob
from core.low_latency_execution import LowLatencyExecutionEngine
from core.prediction.calibration import ProbabilityCalibrator
from core.prediction.edge_calculator import EdgeCalculator
from core.replay.replay_engine import ReplayEngine
from learning.performance_analyzer import PerformanceAnalyzer


def _with_risk_clamp_proof(decision):
    decision.risk_limits_hash = "risk-hash"
    decision.risk_clamp_reason = "risk_clamp_allowed"
    decision.risk_clamp_allowed = True
    decision.policy_hash = "policy-hash"
    decision.model_hash = "model-hash"
    decision.odds_snapshot_hash = "odds-hash"
    decision.feature_snapshot_hash = "feature-hash"
    return decision


class _Risk:
    bankroll = 100_000.0

    def status(self):
        return {
            "bankroll": self.bankroll,
            "drawdown": 0.0,
            "risk_multiplier": 1.0,
            "lose_streak": 0,
            "win_streak": 0,
            "race_risk_used": 0.0,
        }


def test_ipat_adapter_does_not_use_requests():
    source = inspect.getsource(RealIPATClient)
    assert "requests." not in source
    assert "run_in_executor" not in source


def test_ipat_build_from_env_without_credentials_uses_mock(monkeypatch):
    monkeypatch.delenv("IPAT_API_URL", raising=False)
    monkeypatch.delenv("IPAT_API_KEY", raising=False)
    monkeypatch.delenv("IPAT_SECRETS_FILE", raising=False)

    assert isinstance(build_from_env(), MockIPATClient)


def test_ipat_rejects_html_response():
    class _Response:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        async def text(self):
            return "<html>blocked</html>"

    client = RealIPATClient.__new__(RealIPATClient)
    with pytest.raises(RuntimeError, match="HTML response"):
        asyncio.run(client._json_or_raise(_Response()))


def test_edge_calculator_expands_slippage_for_long_odds():
    calculator = EdgeCalculator(odds_slip=0.05)

    assert calculator.slippage_margin(2.0) == 0.05
    assert calculator.slippage_margin(30.0) == pytest.approx(0.15)
    assert calculator.calculate_edge(0.08, 30.0)["safe_odds"] == 25.5


def test_bet_config_race_exposure_clamped_to_eight_percent():
    assert BetConfig().max_race_exposure == pytest.approx(0.08)


def test_shared_circuit_breaker_blocks_bet_executor_and_low_latency_engine(tmp_path):
    breaker = SharedCircuitBreaker(failure_threshold=2, recovery_timeout=60)
    executor = BetExecutor(
        risk_manager=_Risk(),
        log_path=str(tmp_path / "bets.csv"),
        shadow_mode=True,
        safe_mode=True,
        circuit_breaker=breaker,
    )
    engine = LowLatencyExecutionEngine(
        predictor=object(),
        risk_manager=object(),
        ipat_client=object(),
        circuit_breaker=breaker,
    )

    executor.emergency_shutdown("TEST_SHUTDOWN")

    assert breaker.is_open()
    assert executor.is_blocked()
    assert engine.circuit_breaker.is_open()


def test_edge_calculator_uses_regime_adaptive_market_trust():
    calculator = EdgeCalculator(odds_slip=0.0)

    normal = calculator.calculate_edge(0.20, 10.0, regime="NORMAL")
    volatile = calculator.calculate_edge(0.20, 10.0, regime="VOLATILE")

    assert normal["market_trust"] == pytest.approx(0.25)
    assert volatile["market_trust"] == pytest.approx(0.10)
    assert volatile["adjusted_prob"] > normal["adjusted_prob"]


def test_bet_executor_writes_model_and_calibration_replay_keys(tmp_path):
    state_path = tmp_path / "calibration_model.pkl"
    ProbabilityCalibrator(shrink=0.9).save(state_path)
    log_path = tmp_path / "bets.csv"

    executor = BetExecutor(
        risk_manager=_Risk(),
        log_path=str(log_path),
        shadow_mode=True,
        safe_mode=True,
        calibrator_state_path=str(state_path),
    )
    decision = _with_risk_clamp_proof(Decision(
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
    ))

    result = executor.execute_bet(decision)
    row = result["row"]

    assert row["model_version"]
    assert row["model_version"] != ""
    assert row["model_pkl_sha256"]
    assert "model_pkl_sha256" in row
    assert "calibration_last_refit_at" in row
    assert "odds_snapshot_ts" in row
    assert row["calibration_hash"] != "unfitted"

    with log_path.open(encoding="utf-8") as handle:
        persisted = list(csv.DictReader(handle))[-1]
    assert persisted["model_version"] == row["model_version"]
    assert persisted["calibration_hash"] == row["calibration_hash"]

    jsonl = log_path.parent / "decisions.jsonl"
    events = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
    event = next(item for item in events if item["event_type"] == "BetSubmitted")
    assert event["payload"]["model_version"] == row["model_version"]
    assert event["payload"]["calibration_hash"] == row["calibration_hash"]
    assert event["payload"]["model_pkl_sha256"] == row["model_pkl_sha256"]


def test_bet_executor_defaults_to_jsonl_without_csv_report(tmp_path):
    decision_log_path = tmp_path / "decisions.jsonl"
    default_csv = tmp_path / "bets.csv"
    executor = BetExecutor(
        risk_manager=_Risk(),
        decision_log_path=str(decision_log_path),
        shadow_mode=True,
        safe_mode=True,
    )
    decision = _with_risk_clamp_proof(Decision(
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
    ))

    result = executor.execute_bet(decision)

    assert result["blocked"] is False
    assert decision_log_path.exists()
    assert not default_csv.exists()
    events = [json.loads(line) for line in decision_log_path.read_text(encoding="utf-8").splitlines()]
    assert "BetSubmitted" in {event["event_type"] for event in events}
    submitted = next(event for event in events if event["event_type"] == "BetSubmitted")
    assert submitted["payload"]["risk_limits_hash"]


def test_replay_engine_rejects_csv_and_accepts_jsonl(tmp_path):
    class _Loader:
        timestamp_col = "timestamp"

        def get_latest_odds(self, *args, **kwargs):
            return None

        def get_latest_features(self, *args, **kwargs):
            return None

        def get_calibration_state(self, *args, **kwargs):
            return None

    csv_path = tmp_path / "bets.csv"
    csv_path.write_text("timestamp,race_id\n2026-01-01T00:00:00,R1\n", encoding="utf-8")
    jsonl_path = tmp_path / "decisions.jsonl"
    jsonl_path.write_text(
        json.dumps({
            "event": "bet_executed",
            "payload": {
                "timestamp": "2026-01-01T00:00:00",
                "race_id": "R1",
                "selection": "H1",
                "model_version": "abc",
            },
        }) + "\n",
        encoding="utf-8",
    )
    replay = ReplayEngine(loader=_Loader())

    with pytest.raises(ValueError, match="JSONL"):
        replay.replay(csv_path)

    report = replay.replay(jsonl_path)
    assert report["summary"]["total"] == 1


def test_calibration_refit_pkl_roundtrip(tmp_path):
    bets_path = tmp_path / "bets.csv"
    state_path = tmp_path / "calibration_model.pkl"
    rows = []
    for idx in range(40):
        probability = 0.20 if idx < 20 else 0.60
        hit = 1 if idx % 2 == 0 else 0
        rows.append({"probability": probability, "hit": hit})
    pd.DataFrame(rows).to_csv(bets_path, index=False)

    job = CalibrationRefitJob(
        bets_log_path=str(bets_path),
        calibrator_path=str(state_path),
        min_samples=10,
        auto_refit_enabled=True,
        weekend_embargo=False,
    )

    result = job.fit_from_bets_log()
    assert result["status"] == "FITTED"
    assert state_path.exists()
    assert state_path.stat().st_size > 0
    assert result["calibration_hash"]

    loaded = job.load_calibrator()
    assert loaded.bin_edges is not None
    assert loaded.bin_factors is not None
    assert loaded.calibrate(0.25) == pytest.approx(
        ProbabilityCalibrator.load(state_path).calibrate(0.25)
    )


def test_calibration_refit_migrates_legacy_json_to_pkl(tmp_path):
    state_path = tmp_path / "calibration_model.pkl"
    legacy_path = tmp_path / "calibrator_state.json"
    legacy_path.write_text(
        '{"shrink":0.9,"min_prob":0.01,"max_prob":0.95,'
        '"bin_edges":[0,0.5,1],"bin_factors":[1.1,0.9]}',
        encoding="utf-8",
    )

    job = CalibrationRefitJob(
        calibrator_path=str(state_path),
        legacy_json_path=str(legacy_path),
        auto_refit_enabled=False,
    )

    loaded = job.load_calibrator()
    assert state_path.exists()
    assert loaded.bin_edges is not None
    assert loaded.bin_factors is not None


def test_corrupt_calibration_pkl_falls_back_to_shrink_only(tmp_path):
    state_path = tmp_path / "calibration_model.pkl"
    state_path.write_bytes(b"not a pickle")
    job = CalibrationRefitJob(
        calibrator_path=str(state_path),
        legacy_json_path=str(tmp_path / "missing.json"),
        auto_refit_enabled=False,
    )

    loaded = job.load_calibrator()
    assert loaded.bin_edges is None
    assert loaded.bin_factors is None


def test_dashboard_is_read_only_monitoring_surface():
    app = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    control = (ROOT / "dashboard" / "control_panel.py").read_text(encoding="utf-8")
    combined = app + "\n" + control

    assert "time.sleep" not in combined
    assert "st.rerun" not in combined
    assert "run_cycle(" not in combined
    assert "SystemOrchestrator" not in combined


def test_performance_analyzer_caches_by_file_mtime(tmp_path, monkeypatch):
    path = tmp_path / "bets.csv"
    pd.DataFrame(
        [{
            "profit": 100.0,
            "stake": 100.0,
            "probability": 0.4,
            "hit": 1,
            "bankroll": 100000.0,
            "odds": 3.0,
            "edge": 0.1,
            "expected_value": 0.2,
        }]
    ).to_csv(path, index=False)

    calls = {"count": 0}
    real_read_csv = pd.read_csv

    def counted_read_csv(*args, **kwargs):
        calls["count"] += 1
        return real_read_csv(*args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", counted_read_csv)
    analyzer = PerformanceAnalyzer()

    first = analyzer.analyze(str(path))
    second = analyzer.analyze(str(path))

    assert first == second
    assert calls["count"] == 1


def test_phase1_readiness_requires_300_shadow_bets_and_metric_thresholds(tmp_path):
    path = tmp_path / "bets.csv"
    rows = []
    for idx in range(300):
        hit = 1 if idx % 4 == 0 else 0
        rows.append({
            "mode": "SHADOW_MODE",
            "profit": 1.0,
            "stake": 100.0,
            "probability": 0.25,
            "hit": hit,
            "bankroll": 100000.0,
            "odds": 5.0,
            "edge": 0.1,
            "expected_value": 0.25,
            "expected_value_per_unit": 0.25,
        })
    pd.DataFrame(rows).to_csv(path, index=False)

    readiness = PerformanceAnalyzer().analyze(str(path))["phase1_readiness"]

    assert readiness["ready"] is True
    assert readiness["shadow_bets"] == 300
    assert readiness["checks"]["shadow_bets_300"] is True


def test_system_orchestrator_has_single_definition():
    source = (ROOT / "core" / "system_orchestrator.py").read_text(encoding="utf-8")
    assert source.count("class SystemOrchestrator") == 1


def test_project_empty_stubs_removed_from_runtime_tree():
    excluded_parts = {".venv", "logs", "reports", "reports-gh", "results", "__pycache__"}
    empty = []
    for base in (ROOT / "core", ROOT / "research" / "archived"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.stat().st_size != 0:
                continue
            if any(part in excluded_parts for part in path.parts):
                continue
            empty.append(path.relative_to(ROOT).as_posix())

    assert empty == []
