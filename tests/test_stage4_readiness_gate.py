from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.decision_engine import Decision
from core.execution.bet_executor import BetExecutor
from schemas.audit_event import build_audit_event
from schemas.decision_event import REQUIRED_HASH_FIELDS
from scripts.stage4_evidence_bundle import build_evidence_bundle
from scripts.derive_bets_csv_from_decisions import derive
from scripts.stage4_rehearsal_evidence import PREFLIGHT_CHECKS, run_rehearsal_evidence
from scripts.stage4_readiness_gate import (
    CRITICAL_PATH_COVERAGE_FILES,
    _event_chain_gate,
    evaluate_gate,
    expected_fail_only_shadow_days,
)
from scripts.stage4_rubric_v2_3_report import build_report as build_v2_3_report


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _payload(**overrides):
    data = {field: f"{field}-hash" for field in REQUIRED_HASH_FIELDS}
    data.update(
        {
            "decision_id": "D1",
            "selection_id": "H1",
            "execution_status": "SHADOW",
            "shadow_mode": True,
        }
    )
    data.update(overrides)
    return data


def _chain_for_day(day: datetime, previous_hash: str | None, *, include_risk: bool = True, stale: bool = False):
    events = []
    race_id = f"R{day.strftime('%Y%m%d')}"
    base_payload = _payload(race_id=race_id, occurred_at_utc=day.isoformat())
    specs = [
        ("OddsSnapshotReceived", {"odds_snapshot_hash": base_payload["odds_snapshot_hash"]}),
        ("FeatureSnapshotBuilt", {"feature_snapshot_hash": base_payload["feature_snapshot_hash"]}),
        ("PredictionMade", {"model_hash": base_payload["model_hash"]}),
    ]
    if include_risk:
        specs.append(("RiskClampEvaluated", {"allowed": True, "risk_limits_hash": "risk-hash", "stale_data": stale}))
    specs.extend(
        [
            ("BetSubmitted", base_payload),
            ("BetRejected", {"reason": "shadow_mode", "execution_status": "SHADOW", "shadow_mode": True}),
            ("RaceSettled", {"result": "shadow_settled"}),
            ("BankrollUpdated", {"bankroll_hash": "bankroll-hash"}),
        ]
    )
    for idx, (event_type, payload) in enumerate(specs):
        event = build_audit_event(
            event_id=f"{race_id}-{idx}",
            event_type=event_type,
            occurred_at_utc=day.isoformat(),
            race_id=race_id,
            payload=payload,
            previous_hash=previous_hash,
        )
        events.append(event.to_dict())
        previous_hash = event.entry_hash
    return events, previous_hash


def _write_decisions(path: Path, *, days: int = 30, include_risk: bool = True, missing_hash: bool = False, stale: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    all_events = []
    previous_hash = None
    for offset in range(days):
        events, previous_hash = _chain_for_day(
            start + timedelta(days=offset),
            previous_hash,
            include_risk=include_risk,
            stale=stale,
        )
        all_events.extend(events)
    if missing_hash:
        all_events[-4]["payload"]["risk_limits_hash"] = ""
    path.write_text("\n".join(json.dumps(event) for event in all_events) + "\n", encoding="utf-8")


def _write_market(outdir: Path, *, present: bool = True) -> None:
    if not present:
        return
    _write_csv(
        outdir / "variant_summary.csv",
        [
            {"variant": "full", "available": "True", "market_copy_score": "0.42"},
            {"variant": "no_odds", "available": "True", "market_copy_score": ""},
            {"variant": "market_only", "available": "True", "market_copy_score": ""},
            {"variant": "early_odds_only", "available": "True", "market_copy_score": ""},
            {"variant": "closing_odds", "available": "True", "market_copy_score": ""},
        ],
    )
    _write_csv(
        outdir / "odds_regime_summary.csv",
        [
            {"variant": "full", "odds_regime": "FAVORITE_HEAVY", "bets": "1", "roi_pct": "100"},
            {"variant": "full", "odds_regime": "LONGSHOT", "bets": "2", "roi_pct": "95"},
            {"variant": "full", "odds_regime": "DEEP_LONGSHOT", "bets": "3", "roi_pct": "90"},
        ],
    )
    _write_csv(
        outdir / "race_class_summary.csv",
        [{"variant": "full", "race_class": "OPEN", "roi_pct": "100"}],
    )
    _write_csv(
        outdir / "odds_perturbation_summary.csv",
        [
            {
                "variant": "full",
                "scenario": "odds_down_10pct",
                "avg_abs_market_prob_delta": "0.01",
            },
            {
                "variant": "full",
                "scenario": "odds_up_10pct",
                "avg_abs_market_prob_delta": "0.02",
            }
        ],
    )


def _write_common_artifacts(tmp_path: Path, *, replay_summary: dict | None = None, market: bool = True):
    _write_json(tmp_path / ".ci_latency.json", {"p50": 10, "p95": 20, "p99": 30, "p999": 100, "timeout_rate": 0})
    _write_json(
        tmp_path / "replay_report.json",
        {"summary": replay_summary or {"replay_mismatch_count": 0, "snapshot_after_decision": 0, "missing_hash": 0}},
    )
    _write_market(tmp_path / "results" / "market_dependency", present=market)
    _write_csv(tmp_path / "derived" / "bets.csv", [{"race_id": "R1", "risk_limits_hash": "risk-hash"}])
    _write_coverage(tmp_path / "reports" / "stage4" / "critical_path_coverage.json")
    _write_json(
        tmp_path / "reports" / "stage4" / "bet_type_metrics.json",
        {
            "bet_type_metrics": [
                {"bet_type": "win", "mode": "production_candidate"},
                {"bet_type": "place", "mode": "production_candidate"},
                {"bet_type": "wide", "mode": "production_candidate"},
                {"bet_type": "quinella", "mode": "shadow_only"},
                {"bet_type": "trio", "mode": "shadow_only"},
                {"bet_type": "exacta", "mode": "disabled"},
                {"bet_type": "trifecta", "mode": "disabled"},
            ],
            "production_candidate_bet_types": ["win", "place", "wide"],
            "shadow_only_bet_types": ["quinella", "trio"],
            "disabled_bet_types": ["exacta", "trifecta"],
            "shadow_only_violation_count": 0,
            "disabled_bet_type_candidate_count": 0,
            "production_execution_unknown_bet_type_count": 0,
            "bet_type_missing_count": 0,
            "old_win_compat_conversion_count": 1,
        },
    )
    _write_json(
        tmp_path / "reports" / "stage4" / "rubric_v2_3_compliance.json",
        {"final_stage4_rank": "A", "release_recommendation": "RELEASE_READY"},
    )


def _write_coverage(path: Path, *, covered_branches: int = 10, num_branches: int = 10) -> None:
    _write_json(
        path,
        {
            "files": {
                target: {
                    "summary": {
                        "num_branches": num_branches,
                        "covered_branches": covered_branches,
                        "percent_covered": 100.0 if num_branches == 0 else (covered_branches / num_branches) * 100.0,
                    }
                }
                for target in CRITICAL_PATH_COVERAGE_FILES
            }
        },
    )


def _write_preflight_status(path: Path, *, passed: bool = True) -> None:
    _write_json(path, {key: passed for key in PREFLIGHT_CHECKS if key != "stage4_release_gate_passed"})


def _write_preflight_evidence(path: Path) -> None:
    evidence_dir = path.parent / "preflight_drills"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for key in PREFLIGHT_CHECKS:
        if key == "stage4_release_gate_passed":
            continue
        _write_json(evidence_dir / f"{key}.json", {"passed": True, "evidence": f"{key} drill completed"})


def _bundle(tmp_path: Path, *, optional: bool = False):
    return build_evidence_bundle(
        decision_log=tmp_path / "logs" / "decisions.jsonl",
        latency=tmp_path / ".ci_latency.json",
        market_outdir=tmp_path / "results" / "market_dependency",
        derived_bets=tmp_path / "derived" / "bets.csv",
        coverage_json=tmp_path / "reports" / "stage4" / "critical_path_coverage.json",
        output_dir=tmp_path / "reports" / "stage4",
        input_replay_report=tmp_path / "replay_report.json",
        bet_type_metrics=tmp_path / "reports" / "stage4" / "bet_type_metrics.json",
        rubric_v2_3_report=tmp_path / "reports" / "stage4" / "rubric_v2_3_compliance.json",
        optional=optional,
    )


def _evaluate(tmp_path: Path):
    return evaluate_gate(
        decision_log=tmp_path / "logs" / "decisions.jsonl",
        latency=tmp_path / ".ci_latency.json",
        market_outdir=tmp_path / "results" / "market_dependency",
        derived_bets=tmp_path / "derived" / "bets.csv",
        coverage_json=tmp_path / "reports" / "stage4" / "critical_path_coverage.json",
        replay_report=tmp_path / "replay_report.json",
    )


class _StubRisk:
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


def _decision_with_proof():
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
    )
    decision.risk_limits_hash = "risk-hash"
    decision.risk_clamp_reason = "risk_clamp_allowed"
    decision.risk_clamp_allowed = True
    decision.policy_hash = "policy-hash"
    decision.model_hash = "model-hash"
    decision.odds_snapshot_hash = "odds-hash"
    decision.feature_snapshot_hash = "feature-hash"
    return decision


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_stage4_gate_passes_with_clean_30_day_shadow_evidence(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)

    result = _evaluate(tmp_path)

    assert result.passed
    assert result.checks["shadow_coverage"]["calendar_days"] == 30
    report = result.to_dict()
    assert report["evidence_gate"]["passed"] is True
    assert report["metric_gate"]["passed"] is True
    assert report["stage4_verdict"] == "PASS"


def test_derived_bets_csv_preserves_audit_trace_keys(tmp_path):
    decision_log = tmp_path / "logs" / "decisions.jsonl"
    _write_decisions(decision_log, days=1)
    derived_bets = tmp_path / "derived" / "bets.csv"

    row_count = derive(decision_log, derived_bets)

    assert row_count > 0
    with derived_bets.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected_audit_fields = [
            "decision_id",
            "decision_time_utc",
            "event_id",
            "event_type",
            "occurred_at_utc",
            "entry_hash",
            "previous_hash",
            "bankroll_hash",
            "feature_snapshot_hash",
            "odds_snapshot_hash",
            "model_hash",
            "calibration_hash",
            "policy_hash",
            "risk_limits_hash",
            "execution_status",
            "safe_mode",
            "shadow_mode",
        ]
        assert reader.fieldnames[: len(expected_audit_fields)] == expected_audit_fields
        assert len(reader.fieldnames) == len(set(reader.fieldnames))
        rows = list(reader)

    submitted = next(row for row in rows if row["event_type"] == "BetSubmitted")
    assert submitted["decision_id"] == "D1"
    assert submitted["decision_time_utc"]
    assert submitted["entry_hash"]
    assert submitted["bankroll_hash"] == "bankroll_hash-hash"
    assert submitted["feature_snapshot_hash"] == "feature_snapshot_hash-hash"
    assert submitted["odds_snapshot_hash"] == "odds_snapshot_hash-hash"
    assert submitted["model_hash"] == "model_hash-hash"
    assert submitted["calibration_hash"] == "calibration_hash-hash"
    assert submitted["policy_hash"] == "policy_hash-hash"
    assert submitted["risk_limits_hash"] == "risk_limits_hash-hash"
    assert submitted["execution_status"] == "SHADOW"
    assert submitted["shadow_mode"] == "True"


def test_stage4_gate_fails_on_29_days(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl", days=29)
    _write_common_artifacts(tmp_path)

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "shadow_coverage" in result.failures
    report = result.to_dict()
    assert report["blocking_reasons"] == ["shadow_coverage.calendar_days < 30"]
    assert report["non_shadow_blockers"] == []
    assert report["shadow_days"] == 29
    assert report["required_shadow_days"] == 30
    assert report["expected_fail_only_shadow_days"] is True
    assert expected_fail_only_shadow_days(report) is True
    assert report["evidence_gate"]["failures"] == ["shadow_coverage"]
    assert report["metric_gate"]["failures"] == []


def test_stage4_gate_fails_on_riskclamp_bypass(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl", include_risk=False)
    _write_common_artifacts(tmp_path)

    result = _evaluate(tmp_path)

    assert not result.passed
    assert result.checks["event_chain"]["riskclamp_bypass"] > 0


def test_stage4_gate_fails_on_replay_mismatch(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path, replay_summary={"replay_mismatch_count": 1, "snapshot_after_decision": 0, "missing_hash": 0})

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "replay" in result.failures
    assert "replay.replay_mismatch_count > 0" in result.to_dict()["non_shadow_blockers"]


def test_replay_engine_accepts_audit_event_chain_without_external_snapshots(tmp_path):
    decision_log = tmp_path / "logs" / "decisions.jsonl"
    _write_decisions(decision_log, days=1)

    from core.replay.historical_snapshot_loader import HistoricalSnapshotLoader
    from core.replay.replay_engine import ReplayEngine

    report = ReplayEngine(loader=HistoricalSnapshotLoader()).replay(decision_log)

    assert report["summary"]["replay_mismatch_count"] == 0
    assert report["summary"]["missing_hash"] == 0
    assert report["summary"]["snapshot_after_decision"] == 0


def test_stage4_gate_fails_on_missing_hash(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl", missing_hash=True)
    _write_common_artifacts(tmp_path)

    result = _evaluate(tmp_path)

    assert not result.passed
    assert result.checks["payload_hashes"]["missing_payload_hash"] > 0


def test_stage4_gate_fails_on_stale_snapshot_bet(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl", stale=True)
    _write_common_artifacts(tmp_path)

    result = _evaluate(tmp_path)

    assert not result.passed
    assert result.checks["event_chain"]["stale_data_bet"] > 0


def test_stage4_gate_fails_on_timeout_rate(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    _write_json(tmp_path / ".ci_latency.json", {"p50": 10, "p95": 20, "p99": 30, "p999": 100, "timeout_rate": 0.01})

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "latency" in result.failures
    assert result.to_dict()["metric_gate"]["failures"] == ["latency"]


def test_stage4_gate_fails_metric_on_p99_baseline_regression(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    _write_json(
        tmp_path / ".ci_latency.json",
        {"p50": 10, "p95": 20, "p99": 140, "p999": 150, "timeout_rate": 0, "baseline_p99": 100},
    )

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "latency" in result.failures
    assert "latency_regression_rate >= 30%" in result.checks["latency"]["failures"]


def test_stage4_gate_fails_evidence_when_coverage_json_missing(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    (tmp_path / "reports" / "stage4" / "critical_path_coverage.json").unlink()

    result = _evaluate(tmp_path)
    report = result.to_dict()

    assert not result.passed
    assert "critical_path_coverage" in report["evidence_gate"]["failures"]
    assert "critical_path_coverage.coverage_json missing" in report["blocking_reasons"]


def test_stage4_gate_fails_metric_when_branch_coverage_under_80(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    _write_coverage(tmp_path / "reports" / "stage4" / "critical_path_coverage.json", covered_branches=7, num_branches=10)

    result = _evaluate(tmp_path)
    report = result.to_dict()

    assert not result.passed
    assert "critical_path_coverage" in report["metric_gate"]["failures"]
    assert "critical_path_coverage.branch_coverage < 80" in report["blocking_reasons"]


def test_stage4_gate_fails_on_missing_market_dependency_evidence(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path, market=False)

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "market_dependency" in result.failures


def test_stage4_gate_fails_on_missing_odds_perturbation_evidence(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    (tmp_path / "results" / "market_dependency" / "odds_perturbation_summary.csv").unlink()

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "market_dependency" in result.failures
    assert any("odds_perturbation_summary.csv" in item for item in result.checks["market_dependency"]["missing_files"])


def test_stage4_gate_fails_when_early_odds_evidence_is_unavailable(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    _write_csv(
        tmp_path / "results" / "market_dependency" / "variant_summary.csv",
        [
            {"variant": "full", "available": "True", "market_copy_score": "0.42", "reason": ""},
            {"variant": "no_odds", "available": "True", "market_copy_score": "", "reason": ""},
            {"variant": "market_only", "available": "True", "market_copy_score": "", "reason": ""},
            {"variant": "early_odds_only", "available": "False", "market_copy_score": "", "reason": "no matching features"},
            {"variant": "closing_odds", "available": "True", "market_copy_score": "", "reason": ""},
        ],
    )

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "market_dependency" in result.failures
    assert result.checks["market_dependency"]["unavailable_variants"] == ["early_odds_only"]
    assert result.to_dict()["expected_fail_only_shadow_days"] is False


def test_stage4_gate_fails_on_zero_bet_or_non_numeric_roi_bucket(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    _write_csv(
        tmp_path / "results" / "market_dependency" / "odds_regime_summary.csv",
        [
            {"variant": "full", "odds_regime": "FAVORITE_HEAVY", "bets": "0", "roi_pct": "100"},
            {"variant": "full", "odds_regime": "LONGSHOT", "bets": "2", "roi_pct": "not-a-number"},
            {"variant": "full", "odds_regime": "DEEP_LONGSHOT", "bets": "3", "roi_pct": "90"},
        ],
    )

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "market_dependency" in result.failures
    assert len(result.checks["market_dependency"]["invalid_odds_buckets"]) == 2


def test_stage4_gate_fails_on_non_numeric_market_copy_score(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    _write_csv(
        tmp_path / "results" / "market_dependency" / "variant_summary.csv",
        [
            {"variant": "full", "available": "True", "market_copy_score": ""},
            {"variant": "no_odds", "available": "True", "market_copy_score": ""},
            {"variant": "market_only", "available": "True", "market_copy_score": ""},
            {"variant": "early_odds_only", "available": "True", "market_copy_score": ""},
            {"variant": "closing_odds", "available": "True", "market_copy_score": ""},
        ],
    )

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "market_dependency" in result.failures
    assert result.checks["market_dependency"]["market_copy_score"] is None


def test_stage4_gate_fails_on_one_sided_odds_perturbation(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    _write_csv(
        tmp_path / "results" / "market_dependency" / "odds_perturbation_summary.csv",
        [
            {
                "variant": "full",
                "scenario": "odds_down_10pct",
                "avg_abs_market_prob_delta": "0.01",
            }
        ],
    )

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "market_dependency" in result.failures
    assert result.checks["market_dependency"]["missing_perturbations"] == ["odds_up_10pct"]


def test_stage4_event_chain_accepts_bet_executor_generated_shadow_jsonl(tmp_path):
    decision_log = tmp_path / "logs" / "decisions.jsonl"
    executor = BetExecutor(
        risk_manager=_StubRisk(),
        decision_log_path=str(decision_log),
        csv_report_path=str(tmp_path / "derived" / "bets.csv"),
        shadow_mode=True,
        safe_mode=True,
    )
    decision = _decision_with_proof()

    executor.execute_bet(decision)
    executor.update_result(decision, hit=1, profit=4500.0)

    report = _event_chain_gate(_read_jsonl(decision_log))
    assert report["passed"] is True
    assert report["bet_submitted"] == 1
    assert report["riskclamp_bypass"] == 0


def test_stage4_gate_rejects_legacy_bet_executed_only_jsonl(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = []
    for offset in range(30):
        day = start + timedelta(days=offset)
        events.append(
            {
                "event": "bet_executed",
                "timestamp": day.isoformat(),
                "payload": _payload(race_id=f"R{offset}", timestamp=day.isoformat()),
                "entry_hash": f"legacy-{offset}",
            }
        )
    path = tmp_path / "logs" / "decisions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    _write_common_artifacts(tmp_path)

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "event_chain" in result.failures
    assert result.checks["event_chain"]["bet_submitted"] == 0


def test_stage4_gate_fails_on_chain_mismatch(tmp_path):
    path = tmp_path / "logs" / "decisions.jsonl"
    _write_decisions(path)
    events = _read_jsonl(path)
    events[1]["previous_hash"] = "wrong"
    events[1]["entry_hash"] = build_audit_event(
        event_id=events[1]["event_id"],
        event_type=events[1]["event_type"],
        occurred_at_utc=events[1]["occurred_at_utc"],
        race_id=events[1]["race_id"],
        payload=events[1]["payload"],
        previous_hash="wrong",
    ).entry_hash
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    _write_common_artifacts(tmp_path)

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "event_chain" in result.failures
    assert result.checks["event_chain"]["chain_mismatch"] > 0


def test_stage4_gate_fails_on_missing_event_envelope_hash(tmp_path):
    path = tmp_path / "logs" / "decisions.jsonl"
    _write_decisions(path)
    events = _read_jsonl(path)
    events[0]["entry_hash"] = ""
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    _write_common_artifacts(tmp_path)

    result = _evaluate(tmp_path)

    assert not result.passed
    assert "audit_envelopes" in result.failures


def test_stage4_evidence_bundle_passes_with_clean_30_day_shadow_evidence(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)

    result = _bundle(tmp_path)

    assert result["passed"] is True
    assert (tmp_path / "reports" / "stage4" / "evidence_summary.json").exists()
    assert (tmp_path / "reports" / "stage4" / "replay_report.json").exists()


def test_stage4_evidence_bundle_records_v2_3_evidence_paths(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    bet_type_metrics = tmp_path / "reports" / "stage4" / "bet_type_metrics.json"
    rubric_v2_3 = tmp_path / "reports" / "stage4" / "rubric_v2_3_compliance.json"
    _write_json(bet_type_metrics, {"production_candidate_bet_types": ["win", "place", "wide"]})
    _write_json(rubric_v2_3, {"final_stage4_rank": "A", "release_recommendation": "RELEASE_READY"})

    result = build_evidence_bundle(
        decision_log=tmp_path / "logs" / "decisions.jsonl",
        latency=tmp_path / ".ci_latency.json",
        market_outdir=tmp_path / "results" / "market_dependency",
        derived_bets=tmp_path / "derived" / "bets.csv",
        coverage_json=tmp_path / "reports" / "stage4" / "critical_path_coverage.json",
        output_dir=tmp_path / "reports" / "stage4",
        input_replay_report=tmp_path / "replay_report.json",
        bet_type_metrics=bet_type_metrics,
        rubric_v2_3_report=rubric_v2_3,
    )
    summary = json.loads((tmp_path / "reports" / "stage4" / "evidence_summary.json").read_text(encoding="utf-8"))

    assert result["artifacts"]["bet_type_metrics_path"] == str(bet_type_metrics)
    assert result["artifacts"]["rubric_v2_3_report_path"] == str(rubric_v2_3)
    assert summary["bet_type_metrics_path"] == str(bet_type_metrics)
    assert summary["rubric_v2_3_report_path"] == str(rubric_v2_3)
    assert summary["rubric_v2_3_final_rank"] == "A"


def test_stage4_release_gate_dry_run_keeps_v2_3_artifact_dependencies_ordered(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    readiness = tmp_path / "reports" / "stage4" / "readiness_gate.json"
    metrics = tmp_path / "reports" / "stage4" / "bet_type_metrics.json"
    rubric_json = tmp_path / "reports" / "stage4" / "rubric_v2_3_compliance.json"
    rubric_md = tmp_path / "reports" / "stage4" / "rubric_v2_3_compliance.md"

    readiness_payload = _evaluate(tmp_path).to_dict()
    _write_json(readiness, readiness_payload)
    assert readiness.exists()
    assert metrics.exists()

    rubric_payload = build_v2_3_report(
        readiness_path=readiness,
        bet_type_metrics_path=metrics,
        output_json=rubric_json,
        output_md=rubric_md,
    )
    assert rubric_payload["gates"]["bet_type_gate"]["evidence_gate"]["passed"] is True
    assert rubric_json.exists()
    assert rubric_md.exists()

    result = _bundle(tmp_path)
    summary = json.loads((tmp_path / "reports" / "stage4" / "evidence_summary.json").read_text(encoding="utf-8"))

    assert result["artifact_status"]["missing_evidence"] == []
    assert summary["artifacts"]["bet_type_metrics_path"] == str(metrics)
    assert summary["artifacts"]["rubric_v2_3_report_path"] == str(rubric_json)


def test_stage4_evidence_bundle_fails_on_29_days(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl", days=29)
    _write_common_artifacts(tmp_path)

    result = _bundle(tmp_path)

    assert result["passed"] is False
    assert "shadow_coverage" in result["gate"]["failures"]


def test_stage4_evidence_bundle_hard_fails_on_missing_artifact(tmp_path):
    result = _bundle(tmp_path)

    assert result["passed"] is False
    assert result["reason"] == "missing_required_artifacts"
    assert result["skipped"] is False


def test_stage4_evidence_bundle_hard_fails_on_missing_v2_3_evidence(tmp_path):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    (tmp_path / "reports" / "stage4" / "bet_type_metrics.json").unlink()
    (tmp_path / "reports" / "stage4" / "rubric_v2_3_compliance.json").unlink()

    result = _bundle(tmp_path)
    summary = json.loads((tmp_path / "reports" / "stage4" / "evidence_summary.json").read_text(encoding="utf-8"))

    assert result["passed"] is False
    assert result["reason"] == "missing_required_artifacts"
    assert result["artifact_status"]["missing_evidence"] == ["bet_type_metrics", "rubric_v2_3_report"]
    assert summary["artifact_status"]["missing_evidence"] == ["bet_type_metrics", "rubric_v2_3_report"]


def test_stage4_evidence_bundle_optional_mode_does_not_claim_stage4(tmp_path):
    result = _bundle(tmp_path, optional=True)

    assert result["passed"] is False
    assert result["skipped"] is True


def test_stage4_rehearsal_evidence_generates_contract_artifacts(tmp_path, monkeypatch):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    preflight_status = tmp_path / "reports" / "stage4" / "preflight_status.json"
    _write_preflight_status(preflight_status)
    _write_preflight_evidence(preflight_status)

    def fake_market_report(*, input_path, outdir, model_kind, train_ratio, folds):
        _write_market(Path(outdir))
        return {
            "variant_summary": Path(outdir) / "variant_summary.csv",
            "odds_regime_summary": Path(outdir) / "odds_regime_summary.csv",
            "race_class_summary": Path(outdir) / "race_class_summary.csv",
            "odds_perturbation_summary": Path(outdir) / "odds_perturbation_summary.csv",
            "markdown": Path(outdir) / "market_dependency_report.md",
        }

    monkeypatch.setattr("scripts.stage4_rehearsal_evidence.generate_market_dependency_report", fake_market_report)

    result = run_rehearsal_evidence(
        decision_log=tmp_path / "logs" / "decisions.jsonl",
        historical_data=tmp_path / "data" / "historical.csv",
        latency=tmp_path / ".ci_latency.json",
        market_outdir=tmp_path / "results" / "market_dependency",
        derived_bets=tmp_path / "derived" / "bets.csv",
        coverage_json=tmp_path / "reports" / "stage4" / "critical_path_coverage.json",
        output_dir=tmp_path / "reports" / "stage4",
        input_replay_report=tmp_path / "replay_report.json",
        odds_snapshots=None,
        feature_snapshots=None,
        calibration_snapshots=None,
        timestamp_col="timestamp",
        model_kind="boosted",
        train_ratio=0.7,
        folds=3,
        preflight_status=preflight_status,
    )

    assert result["passed"] is True
    assert result["derived_bets_rows"] > 0
    assert (tmp_path / "reports" / "stage4" / "readiness_gate.json").exists()
    assert (tmp_path / "reports" / "stage4" / "limited_production_rehearsal_preflight.json").exists()


def test_stage4_rehearsal_evidence_requires_preflight_drill_files(tmp_path, monkeypatch):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)
    preflight_status = tmp_path / "reports" / "stage4" / "preflight_status.json"
    _write_preflight_status(preflight_status)

    def fake_market_report(*, input_path, outdir, model_kind, train_ratio, folds):
        _write_market(Path(outdir))
        return {
            "variant_summary": Path(outdir) / "variant_summary.csv",
            "odds_regime_summary": Path(outdir) / "odds_regime_summary.csv",
            "race_class_summary": Path(outdir) / "race_class_summary.csv",
            "odds_perturbation_summary": Path(outdir) / "odds_perturbation_summary.csv",
            "markdown": Path(outdir) / "market_dependency_report.md",
        }

    monkeypatch.setattr("scripts.stage4_rehearsal_evidence.generate_market_dependency_report", fake_market_report)

    result = run_rehearsal_evidence(
        decision_log=tmp_path / "logs" / "decisions.jsonl",
        historical_data=tmp_path / "data" / "historical.csv",
        latency=tmp_path / ".ci_latency.json",
        market_outdir=tmp_path / "results" / "market_dependency",
        derived_bets=tmp_path / "derived" / "bets.csv",
        coverage_json=tmp_path / "reports" / "stage4" / "critical_path_coverage.json",
        output_dir=tmp_path / "reports" / "stage4",
        input_replay_report=tmp_path / "replay_report.json",
        odds_snapshots=None,
        feature_snapshots=None,
        calibration_snapshots=None,
        timestamp_col="timestamp",
        model_kind="boosted",
        train_ratio=0.7,
        folds=3,
        preflight_status=preflight_status,
    )

    assert result["bundle"]["passed"] is True
    assert result["passed"] is False
    assert "operator_kill_switch_tested" in result["preflight"]["missing"]


def test_stage4_rehearsal_evidence_blocks_without_preflight_status(tmp_path, monkeypatch):
    _write_decisions(tmp_path / "logs" / "decisions.jsonl")
    _write_common_artifacts(tmp_path)

    def fake_market_report(*, input_path, outdir, model_kind, train_ratio, folds):
        _write_market(Path(outdir))
        return {"variant_summary": Path(outdir) / "variant_summary.csv"}

    monkeypatch.setattr("scripts.stage4_rehearsal_evidence.generate_market_dependency_report", fake_market_report)

    result = run_rehearsal_evidence(
        decision_log=tmp_path / "logs" / "decisions.jsonl",
        historical_data=tmp_path / "data" / "historical.csv",
        latency=tmp_path / ".ci_latency.json",
        market_outdir=tmp_path / "results" / "market_dependency",
        derived_bets=tmp_path / "derived" / "bets.csv",
        coverage_json=tmp_path / "reports" / "stage4" / "critical_path_coverage.json",
        output_dir=tmp_path / "reports" / "stage4",
        input_replay_report=tmp_path / "replay_report.json",
        odds_snapshots=None,
        feature_snapshots=None,
        calibration_snapshots=None,
        timestamp_col="timestamp",
        model_kind="boosted",
        train_ratio=0.7,
        folds=3,
        preflight_status=None,
    )

    assert result["bundle"]["passed"] is True
    assert result["passed"] is False
    assert "operator_kill_switch_tested" in result["preflight"]["missing"]
