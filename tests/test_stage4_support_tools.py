from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.derive_bets_csv_from_decisions import AUDIT_TRACE_FIELDS, derive
from scripts.feature_drift_report import build_feature_drift_report
from scripts.market_dependency_report import generate_report
from scripts.stage4_evidence_blockers_report import build_blockers_report
from scripts.latency_regression_guard import evaluate_latency_regression
from scripts.merge_market_snapshots import merge_market_snapshots
from scripts.shadow_run_from_file import _candidate
from scripts.stage4_current_update import _jsonable_market_plan, choose_market_input
from scripts.stage4_operator_preflight_drills import run_drills
from scripts.stage4_rehearsal_evidence import _preflight_report
from scripts.stage4_rubric_v2_2_report import build_report as build_rubric_report
from scripts.stage4_survivability_report import REPORT_SECTIONS, build_report


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_merge_market_snapshots_adds_real_early_and_closing_columns(tmp_path):
    base = tmp_path / "historical.csv"
    early = tmp_path / "early.csv"
    closing = tmp_path / "closing.csv"
    output = tmp_path / "historical_with_snapshots.csv"
    _write_csv(
        base,
        [
            {"race_id": "R1", "horse_id": "H1", "odds": 3.2, "target_win": 1},
            {"race_id": "R1", "horse_id": "H2", "odds": 8.1, "target_win": 0},
        ],
    )
    _write_csv(
        early,
        [
            {"race_id": "R1", "horse_id": "H1", "snapshot_time": "2026-01-01T00:30:00+00:00", "odds": 3.6},
            {"race_id": "R1", "horse_id": "H2", "snapshot_time": "2026-01-01T00:30:00+00:00", "odds": 7.8},
        ],
    )
    _write_csv(
        closing,
        [
            {"race_id": "R1", "horse_id": "H1", "snapshot_time": "2026-01-01T01:00:00+00:00", "odds": 3.0},
            {"race_id": "R1", "horse_id": "H2", "snapshot_time": "2026-01-01T01:00:00+00:00", "odds": 8.4},
        ],
    )

    report = merge_market_snapshots(
        base_path=base,
        output_path=output,
        join_keys=["race_id", "horse_id"],
        early_snapshot=early,
        closing_snapshot=closing,
    )

    rows = list(csv.DictReader(output.open(newline="", encoding="utf-8")))
    assert report["early"]["matched_rows"] == 2
    assert report["closing"]["matched_rows"] == 2
    assert rows[0]["early_odds"] == "3.6"
    assert rows[0]["closing_odds"] == "3.0"


def test_merge_market_snapshots_requires_snapshot_time(tmp_path):
    base = tmp_path / "historical.csv"
    early = tmp_path / "early.csv"
    _write_csv(base, [{"race_id": "R1", "horse_id": "H1", "odds": 3.2}])
    _write_csv(early, [{"race_id": "R1", "horse_id": "H1", "odds_t30": 3.6}])

    with pytest.raises(ValueError, match="snapshot_time"):
        merge_market_snapshots(
            base_path=base,
            output_path=tmp_path / "out.csv",
            join_keys=["race_id", "horse_id"],
            early_snapshot=early,
        )


def test_merge_market_snapshots_rejects_copy_of_odds_as_early_odds(tmp_path):
    base = tmp_path / "historical.csv"
    early = tmp_path / "early.csv"
    _write_csv(base, [{"race_id": "R1", "horse_id": "H1", "odds": 3.2}])
    _write_csv(early, [{"race_id": "R1", "horse_id": "H1", "snapshot_time": "2026-01-01T00:30:00+00:00", "odds": 3.2}])

    with pytest.raises(ValueError, match="copied from base odds"):
        merge_market_snapshots(
            base_path=base,
            output_path=tmp_path / "out.csv",
            join_keys=["race_id", "horse_id"],
            early_snapshot=early,
        )


def test_merge_market_snapshots_rejects_copy_of_odds_value_as_closing_odds(tmp_path):
    base = tmp_path / "historical.csv"
    closing = tmp_path / "closing.csv"
    _write_csv(base, [{"race_id": "R1", "horse_id": "H1", "odds": 3.4, "odds_value": 3.2}])
    _write_csv(closing, [{"race_id": "R1", "horse_id": "H1", "snapshot_time": "2026-01-01T01:00:00+00:00", "odds": 3.2}])

    with pytest.raises(ValueError, match="copied from base odds_value"):
        merge_market_snapshots(
            base_path=base,
            output_path=tmp_path / "out.csv",
            join_keys=["race_id", "horse_id"],
            closing_snapshot=closing,
        )


def test_merge_market_snapshots_rejects_empty_real_snapshot(tmp_path):
    base = tmp_path / "historical.csv"
    early = tmp_path / "early.csv"
    _write_csv(base, [{"race_id": "R1", "horse_id": "H1", "odds": 3.2}])
    _write_csv(early, [{"race_id": "R1", "horse_id": "H1", "snapshot_time": "2026-01-01T00:30:00+00:00", "odds_t30": ""}])

    with pytest.raises(ValueError, match="no values"):
        merge_market_snapshots(
            base_path=base,
            output_path=tmp_path / "out.csv",
            join_keys=["race_id", "horse_id"],
            early_snapshot=early,
        )


def test_merge_market_snapshots_normalizes_selection_id_snapshot_key(tmp_path):
    base = tmp_path / "historical.csv"
    early = tmp_path / "early.csv"
    output = tmp_path / "out.csv"
    _write_csv(base, [{"race_id": "R1", "horse_id": "H1", "odds": 3.2}])
    _write_csv(
        early,
        [{"race_id": "R1", "selection_id": "H1", "snapshot_time": "2026-01-01T00:30:00+00:00", "odds": 3.7}],
    )

    report = merge_market_snapshots(
        base_path=base,
        output_path=output,
        join_keys=["race_id", "horse_id"],
        early_snapshot=early,
    )

    row = next(csv.DictReader(output.open(newline="", encoding="utf-8")))
    assert report["early"]["matched_rows"] == 1
    assert row["early_odds"] == "3.7"


def test_stage4_current_update_uses_base_when_real_market_snapshots_are_missing(tmp_path):
    base = tmp_path / "historical.csv"
    merged = tmp_path / "historical_with_snapshots.csv"

    plan = choose_market_input(
        base_historical=base,
        merged_historical=merged,
        early_snapshot=tmp_path / "market" / "early_odds.csv",
        closing_snapshot=tmp_path / "market" / "closing_odds.csv",
    )

    assert plan["mode"] == "blocked_missing_real_snapshots"
    assert plan["input"] == base
    assert plan["strict"] is False


def test_stage4_current_update_merges_when_both_real_snapshot_files_exist(tmp_path):
    early = tmp_path / "market" / "early_odds.csv"
    closing = tmp_path / "market" / "closing_odds.csv"
    early.parent.mkdir(parents=True)
    early.write_text("race_id,horse_id,snapshot_time,early_odds\n", encoding="utf-8")
    closing.write_text("race_id,horse_id,snapshot_time,closing_odds\n", encoding="utf-8")
    merged = tmp_path / "historical_with_snapshots.csv"

    plan = choose_market_input(
        base_historical=tmp_path / "historical.csv",
        merged_historical=merged,
        early_snapshot=early,
        closing_snapshot=closing,
    )

    assert plan["mode"] == "merge_real_snapshots"
    assert plan["input"] == merged
    assert plan["strict"] is True


def test_stage4_current_update_reuses_valid_existing_merged_snapshot_dataset(tmp_path):
    merged = tmp_path / "historical_with_snapshots.csv"
    merged.write_text("race_id,horse_id,early_odds,closing_odds\nR1,H1,3.6,3.2\n", encoding="utf-8")
    (tmp_path / "historical_with_snapshots.csv.market_snapshot_report.json").write_text(
        json.dumps(
            {
                "early": {"merged": True, "matched_rows": 1},
                "closing": {"merged": True, "matched_rows": 1},
            }
        ),
        encoding="utf-8",
    )

    plan = choose_market_input(
        base_historical=tmp_path / "historical.csv",
        merged_historical=merged,
        early_snapshot=tmp_path / "market" / "early_odds.csv",
        closing_snapshot=tmp_path / "market" / "closing_odds.csv",
    )

    assert plan["mode"] == "use_existing_merged_snapshots"
    assert plan["input"] == merged
    assert plan["strict"] is True


def test_stage4_current_update_summary_serializes_market_plan_paths(tmp_path):
    plan = _jsonable_market_plan({"mode": "blocked_missing_real_snapshots", "input": tmp_path / "historical.csv"})

    json.dumps(plan)
    assert plan["input"] == str(tmp_path / "historical.csv")


def test_market_dependency_report_marks_real_early_and_closing_snapshots_available(tmp_path):
    input_path = tmp_path / "historical_with_snapshots.csv"
    rows = []
    odds_values = [1.8, 3.5, 9.0, 25.0]
    for race_idx in range(12):
        for horse_idx in range(2):
            odds = odds_values[(race_idx + horse_idx) % len(odds_values)]
            rows.append(
                {
                    "race_id": f"R{race_idx:02d}",
                    "horse_id": f"H{horse_idx}",
                    "race_date": f"2026-01-{race_idx + 1:02d}",
                    "odds": odds,
                    "favorite_rank": horse_idx + 1,
                    "weight_carried": 55 + horse_idx,
                    "age": 3 + horse_idx,
                    "horse_weight": 480 + race_idx + horse_idx,
                    "horse_weight_diff": horse_idx - (race_idx % 2),
                    "avg_finish_last5": 2 + horse_idx,
                    "avg_finish_last3": 2 + horse_idx,
                    "avg_speed_index_last5": 70 + race_idx,
                    "recent_form_score": 0.4 + horse_idx,
                    "last_finish": 1 + horse_idx,
                    "rest_days": 14 + race_idx,
                    "early_odds": odds + 0.4,
                    "closing_odds": odds - 0.2,
                    "target_win": 1 if horse_idx == race_idx % 2 else 0,
                    "race_title": "OPEN",
                }
            )
    _write_csv(input_path, rows)

    generate_report(
        input_path=input_path,
        outdir=tmp_path / "market_dependency",
        model_kind="logistic",
        train_ratio=0.6,
        folds=2,
    )

    summary = {
        row["variant"]: row
        for row in csv.DictReader((tmp_path / "market_dependency" / "variant_summary.csv").open(newline="", encoding="utf-8-sig"))
    }
    assert summary["early_odds_only"]["available"] == "True"
    assert summary["early_odds_only"]["features"] == "early_odds"
    assert summary["closing_odds"]["available"] == "True"
    assert summary["closing_odds"]["features"] == "closing_odds"


def test_stage4_operator_preflight_drills_write_pass_evidence_and_status(tmp_path):
    decision_log = tmp_path / "logs" / "decisions.jsonl"
    derived_bets = tmp_path / "derived" / "bets.csv"
    event = {
        "event_id": "E1",
        "event_type": "BetSubmitted",
        "occurred_at_utc": "2026-01-01T00:00:00+00:00",
        "race_id": "R1",
        "entry_hash": "entry",
        "previous_hash": "prev",
        "payload": {
            "decision_id": "D1",
            "bankroll_hash": "bankroll",
            "feature_snapshot_hash": "feature",
            "odds_snapshot_hash": "odds",
            "model_hash": "model",
            "calibration_hash": "calibration",
            "policy_hash": "policy",
            "risk_limits_hash": "risk",
            "execution_status": "SHADOW",
            "safe_mode": True,
            "shadow_mode": True,
            "selection_id": "H1",
        },
    }
    decision_log.parent.mkdir(parents=True)
    decision_log.write_text(json.dumps(event) + "\n", encoding="utf-8")
    derive(decision_log, derived_bets)

    summary = run_drills(
        output_dir=tmp_path / "reports" / "stage4" / "preflight_drills",
        status_path=tmp_path / "reports" / "stage4" / "preflight_status.json",
        decision_log=decision_log,
        derived_bets=derived_bets,
        operator="pytest",
    )

    assert summary["passed"] is True
    status = json.loads((tmp_path / "reports" / "stage4" / "preflight_status.json").read_text(encoding="utf-8"))
    for key in (
        "operator_kill_switch_tested",
        "manual_override_tested",
        "max_exposure_cap_enforced",
        "bankroll_reconciliation_tested",
        "tax_audit_export_reproduced",
    ):
        assert status[key] is True
    for stem in ("kill_switch", "manual_override", "max_exposure_cap", "bankroll_reconciliation", "tax_audit_export"):
        text = (tmp_path / "reports" / "stage4" / "preflight_drills" / f"{stem}.md").read_text(encoding="utf-8")
        assert "## Result\nPASS" in text


def test_stage4_operator_preflight_drills_do_not_mark_failed_artifact_true(tmp_path):
    decision_log = tmp_path / "logs" / "decisions.jsonl"
    decision_log.parent.mkdir(parents=True)
    decision_log.write_text("", encoding="utf-8")
    derived_bets = tmp_path / "derived" / "bets.csv"
    derived_bets.parent.mkdir(parents=True)
    derived_bets.write_text("decision_id\n", encoding="utf-8")

    summary = run_drills(
        output_dir=tmp_path / "reports" / "stage4" / "preflight_drills",
        status_path=tmp_path / "reports" / "stage4" / "preflight_status.json",
        decision_log=decision_log,
        derived_bets=derived_bets,
        operator="pytest",
        only="tax_audit_export",
    )

    status = json.loads((tmp_path / "reports" / "stage4" / "preflight_status.json").read_text(encoding="utf-8"))
    assert summary["passed"] is False
    assert status["tax_audit_export_reproduced"] is False
    assert "## Result\nFAIL" in (tmp_path / "reports" / "stage4" / "preflight_drills" / "tax_audit_export.md").read_text(encoding="utf-8")


def test_shadow_candidate_requires_real_race_selection_and_valid_odds():
    row = {
        "race_id": "R1",
        "horse_id": "H1",
        "odds": "4.5",
        "speed_index": "0.7",
        "odds_snapshot_hash": "odds-hash",
        "feature_snapshot_hash": "feature-hash",
    }

    candidate = _candidate(row)

    assert candidate["race_id"] == "R1"
    assert candidate["selection"] == "H1"
    assert candidate["features"]["speed_index"] == "0.7"
    assert candidate["odds_snapshot_hash"] == "odds-hash"


def test_shadow_candidate_rejects_invalid_odds():
    with pytest.raises(ValueError, match="invalid odds"):
        _candidate({"race_id": "R1", "horse_id": "H1", "odds": "1.0"})


def test_survivability_report_outputs_required_order_and_machine_keys(tmp_path):
    readiness = tmp_path / "readiness.json"
    replay = tmp_path / "replay.json"
    latency = tmp_path / ".ci_latency.json"
    preflight = tmp_path / "preflight.json"
    derived = tmp_path / "bets.csv"
    output_md = tmp_path / "survivability.md"
    output_json = tmp_path / "survivability.json"

    _write_json(
        readiness,
        {
            "passed": False,
            "failures": ["shadow_coverage", "market_dependency"],
            "checks": {
                "shadow_coverage": {"passed": False, "calendar_days": 1},
                "replay": {"passed": True, "replay_mismatch_count": 0, "missing_hash": 0, "snapshot_after_decision": 0},
                "market_dependency": {"passed": False, "unavailable_variants": ["early_odds_only", "closing_odds"], "missing_odds_buckets": []},
                "event_chain": {"passed": True, "riskclamp_bypass": 0, "stale_data_bet": 0, "missing_audit_hash": 0, "chain_mismatch": 0},
                "audit_envelopes": {"passed": True, "missing_audit_hash": 0},
                "payload_hashes": {"passed": True, "missing_payload_hash": 0},
                "latency": {"passed": True, "p999": 5.0, "timeout_rate": 0.0},
            },
        },
    )
    _write_json(replay, {"summary": {"replay_mismatch_count": 0, "missing_hash": 0, "snapshot_after_decision": 0}})
    _write_json(latency, {"p999": 5.0, "timeout_rate": 0.0})
    _write_json(preflight, {"passed": False, "missing": ["operator_kill_switch_tested"]})
    _write_csv(
        derived,
        [
            {
                "decision_id": "D1",
                "decision_time_utc": "2026-01-01T00:00:00+00:00",
                "entry_hash": "h",
                "bankroll_hash": "b",
                "feature_snapshot_hash": "f",
                "odds_snapshot_hash": "o",
                "model_hash": "m",
                "calibration_hash": "c",
                "policy_hash": "p",
                "execution_status": "SHADOW",
                "safe_mode": True,
                "shadow_mode": True,
            }
        ],
    )

    payload = build_report(
        readiness_path=readiness,
        replay_path=replay,
        latency_path=latency,
        preflight_path=preflight,
        derived_bets_path=derived,
        output_md=output_md,
        output_json=output_json,
    )

    text = output_md.read_text(encoding="utf-8")
    positions = [text.index(f"## {idx}. {section}") for idx, section in enumerate(REPORT_SECTIONS, start=1)]
    assert positions == sorted(positions)
    assert payload["stage"] == "Stage 4.2 Evidence-Blocked Candidate"
    assert payload["production_readiness"]["limited_production_rehearsal"] == "blocked"
    assert {"stage", "production_readiness", "gate_status", "scorecard", "collapse_probability", "blockers"} <= set(payload)
    assert "market_dependency.early_odds_only unavailable" in payload["blockers"]
    assert "Stage4 release gate not passed" not in payload["blockers"]
    assert json.loads(output_json.read_text(encoding="utf-8"))["stage"] == payload["stage"]


def test_evidence_blockers_report_uses_readiness_blocking_reason_names(tmp_path):
    readiness = tmp_path / "readiness.json"
    survivability = tmp_path / "survivability.json"
    output = tmp_path / "evidence_blockers.md"
    _write_json(
        readiness,
        {
            "passed": False,
            "blocking_reasons": [
                "shadow_coverage.calendar_days < 30",
                "market_dependency.early_odds_only unavailable",
            ],
            "non_shadow_blockers": ["market_dependency.early_odds_only unavailable"],
            "shadow_days": 1,
            "required_shadow_days": 30,
        },
    )
    _write_json(
        survivability,
        {
            "stage": "Stage 4.2 Evidence-Blocked Candidate",
            "production_readiness": {"limited_production_rehearsal": "blocked"},
            "collapse_probability": {"range": "11-28%"},
            "blockers": [
                "early_odds_only unavailable",
                "operator preflight not passed",
                "Stage4 release gate not passed",
            ],
        },
    )

    report = build_blockers_report(
        survivability_json=survivability,
        readiness_json=readiness,
        output_md=output,
    )

    text = output.read_text(encoding="utf-8")
    assert report["blockers"] == [
        "shadow_coverage.calendar_days < 30",
        "market_dependency.early_odds_only unavailable",
        "operator preflight not passed",
    ]
    assert "- market_dependency.early_odds_only unavailable" in text
    assert "- early_odds_only unavailable" not in text
    assert "Stage4 release gate not passed" not in text


def test_rubric_v2_2_report_marks_evidence_blocked_and_a6_a_grade(tmp_path):
    readiness = tmp_path / "readiness.json"
    survivability = tmp_path / "survivability.json"
    latency = tmp_path / ".ci_latency.json"
    output_json = tmp_path / "rubric.json"
    output_md = tmp_path / "rubric.md"
    _write_json(
        readiness,
        {
            "stage4_verdict": "EVIDENCE_BLOCKED",
            "blocking_reasons": [
                "shadow_coverage.calendar_days < 30",
                "market_dependency.early_odds_only unavailable",
            ],
            "evidence_gate": {"passed": False, "failures": ["shadow_coverage", "market_dependency"]},
            "metric_gate": {"passed": True, "failures": []},
            "checks": {
                "replay": {"passed": True},
                "payload_hashes": {"passed": True},
                "audit_envelopes": {"passed": True},
                "event_chain": {"passed": True},
                "governance_lint": {"passed": True},
                "critical_path_coverage": {"branch_coverage_pct": 86.3481},
            },
        },
    )
    _write_json(
        survivability,
        {
            "stage": "Stage 4.2 Evidence-Blocked Candidate",
        },
    )
    _write_json(
        latency,
        {
            "baseline_p99": 14.7497,
            "p50": 2.3173,
            "p95": 13.6572,
            "p99": 14.7497,
            "p999": 14.7497,
            "timeout_rate": 0.0,
        },
    )

    payload = build_rubric_report(
        readiness_path=readiness,
        survivability_path=survivability,
        latency_path=latency,
        drift_path=tmp_path / "missing_feature_drift.json",
        output_json=output_json,
        output_md=output_md,
    )

    assert payload["final_rank"]["rank"] == "C"
    assert payload["axes"]["A4"]["grade"] == "A"
    assert payload["axes"]["A5"]["grade"] == "PASS"
    assert payload["axes"]["A6"]["grade"] == "A"
    assert payload["axes"]["A7"]["subaxes"]["A7_3_drift"]["status"] == "NOT_EVALUABLE"
    assert "Evidence Gate not passed" in payload["final_rank"]["reason"]
    assert json.loads(output_json.read_text(encoding="utf-8"))["axes"]["A6"]["details"]["critical_path_branch_coverage"] == 86.3481


def test_derived_bets_csv_contract_and_rejects_missing_decision_id(tmp_path):
    log = tmp_path / "logs" / "decisions.jsonl"
    out = tmp_path / "derived" / "bets.csv"
    event = {
        "event_id": "E1",
        "event_type": "BetSubmitted",
        "occurred_at_utc": "2026-01-01T00:00:00+00:00",
        "race_id": "R1",
        "entry_hash": "entry",
        "previous_hash": "prev",
        "payload": {
            "decision_id": "D1",
            "bankroll_hash": "bankroll",
            "feature_snapshot_hash": "feature",
            "odds_snapshot_hash": "odds",
            "model_hash": "model",
            "calibration_hash": "calibration",
            "policy_hash": "policy",
            "risk_limits_hash": "risk",
            "execution_status": "SHADOW",
            "safe_mode": True,
            "shadow_mode": True,
            "selection_id": "H1",
        },
    }
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps(event) + "\n", encoding="utf-8")

    derive(log, out)
    with out.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames[: len(AUDIT_TRACE_FIELDS)] == AUDIT_TRACE_FIELDS
        row = next(reader)
    assert row["entry_hash"] == "entry"
    assert row["previous_hash"] == "prev"
    assert row["risk_limits_hash"] == "risk"

    event["payload"].pop("decision_id")
    log.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing decision_id"):
        derive(log, out)


def test_preflight_rejects_true_without_pass_marker_and_accepts_pass_evidence(tmp_path):
    status = tmp_path / "reports" / "stage4" / "preflight_status.json"
    drill_dir = status.parent / "preflight_drills"
    drill_dir.mkdir(parents=True)
    checks = {
        "operator_kill_switch_tested": True,
        "manual_override_tested": False,
        "max_exposure_cap_enforced": False,
        "bankroll_reconciliation_tested": False,
        "tax_audit_export_reproduced": False,
        "evidence_paths": {"kill_switch": "reports/stage4/preflight_drills/kill_switch.md"},
    }
    status.write_text(json.dumps(checks), encoding="utf-8")
    (drill_dir / "kill_switch.md").write_text("# Drill\n\n## Result\nPENDING\n", encoding="utf-8")

    report = _preflight_report(readiness_passed=True, status_path=status)
    assert "operator_kill_switch_tested" in report["missing"]

    (drill_dir / "kill_switch.md").write_text("# Drill\n\n## Result\nPASS\n", encoding="utf-8")
    report = _preflight_report(readiness_passed=True, status_path=status)
    assert "operator_kill_switch_tested" not in report["missing"]


def test_preflight_status_requires_all_fields(tmp_path):
    status = tmp_path / "reports" / "stage4" / "preflight_status.json"
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({"operator_kill_switch_tested": False}), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required fields"):
        _preflight_report(readiness_passed=False, status_path=status)


def test_latency_regression_guard_records_delta_and_rejects_large_regression(tmp_path):
    previous = tmp_path / "previous.json"
    current = tmp_path / "current.json"
    previous.write_text(json.dumps({"p99": 10.0, "p999": 12.0, "timeout_rate": 0.0}), encoding="utf-8")
    current.write_text(json.dumps({"p99": 14.0, "p999": 16.0, "timeout_rate": 0.0}), encoding="utf-8")

    report = evaluate_latency_regression(current_path=current, previous_path=previous)

    assert report["passed"] is False
    assert report["baseline_p99"] == 10.0
    assert report["current_p99"] == 14.0
    assert report["current_p999"] == 16.0
    assert report["delta_pct"] == 40.0
    assert "p99 regression >= 30%" in report["failures"]


def test_feature_drift_report_outputs_top_feature_and_odds_psi(tmp_path):
    baseline = tmp_path / "baseline.csv"
    current = tmp_path / "current.csv"
    output = tmp_path / "feature_drift_report.json"
    _write_csv(
        baseline,
        [
            {"odds": 2.0, "favorite_rank": 1, "weight_carried": 55, "target_win": 1},
            {"odds": 3.0, "favorite_rank": 2, "weight_carried": 56, "target_win": 0},
            {"odds": 4.0, "favorite_rank": 3, "weight_carried": 57, "target_win": 0},
        ],
    )
    _write_csv(
        current,
        [
            {"odds": 2.1, "favorite_rank": 1, "weight_carried": 55, "target_win": 1},
            {"odds": 3.2, "favorite_rank": 2, "weight_carried": 56, "target_win": 0},
            {"odds": 4.4, "favorite_rank": 3, "weight_carried": 57, "target_win": 0},
        ],
    )

    report = build_feature_drift_report(
        baseline_path=baseline,
        current_path=current,
        output_path=output,
        top_n=2,
        bins=3,
    )

    assert output.exists()
    assert report["top_features"] == ["odds", "favorite_rank"]
    assert "odds_distribution" in report["psi"]
    assert report["odds_distribution_psi"] is not None
