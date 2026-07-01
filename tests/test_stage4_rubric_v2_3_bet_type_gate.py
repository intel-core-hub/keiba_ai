from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.stage4_rubric_v2_3_report import build_report, evaluate_bet_type_gate


def _metrics_payload(**overrides):
    payload = {
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
    }
    payload.update(overrides)
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_bet_type_metrics_missing_blocks_evidence_gate(tmp_path):
    gate = evaluate_bet_type_gate(tmp_path / "missing.json")

    assert gate["evidence_gate"]["passed"] is False
    assert "bet_type_metrics_missing" in gate["evidence_gate"]["failures"]


def test_v2_3_release_gate_fails_when_bet_type_metrics_missing(tmp_path):
    readiness = tmp_path / "readiness_gate.json"
    _write_json(readiness, {"evidence_gate": {"passed": True, "failures": []}, "metric_gate": {"passed": True, "failures": []}})

    payload = build_report(
        readiness_path=readiness,
        bet_type_metrics_path=tmp_path / "missing_bet_type_metrics.json",
        output_json=tmp_path / "rubric_v2_3.json",
        output_md=tmp_path / "rubric_v2_3.md",
    )

    assert payload["gates"]["evidence_gate"]["passed"] is False
    assert payload["final_stage4_rank"] == "C"
    assert payload["release_recommendation"] == "NOT_RELEASE_READY"


def test_shadow_only_violation_blocks_metric_gate(tmp_path):
    path = tmp_path / "bet_type_metrics.json"
    _write_json(path, _metrics_payload(shadow_only_violation_count=1))

    gate = evaluate_bet_type_gate(path)

    assert gate["evidence_gate"]["passed"] is True
    assert gate["metric_gate"]["passed"] is False
    assert "shadow_only_violation_count" in gate["metric_gate"]["failures"]


def test_disabled_candidate_blocks_metric_gate(tmp_path):
    path = tmp_path / "bet_type_metrics.json"
    _write_json(path, _metrics_payload(disabled_bet_type_candidate_count=1))

    gate = evaluate_bet_type_gate(path)

    assert gate["metric_gate"]["passed"] is False
    assert "disabled_bet_type_candidate_count" in gate["metric_gate"]["failures"]


def test_expected_bet_type_sets_are_reported(tmp_path):
    metrics = tmp_path / "bet_type_metrics.json"
    readiness = tmp_path / "readiness_gate.json"
    _write_json(metrics, _metrics_payload())
    _write_json(readiness, {"evidence_gate": {"passed": True, "failures": []}, "metric_gate": {"passed": True, "failures": []}})

    payload = build_report(
        readiness_path=readiness,
        bet_type_metrics_path=metrics,
        output_json=tmp_path / "rubric_v2_3.json",
        output_md=tmp_path / "rubric_v2_3.md",
    )

    assert payload["production_candidate_bet_types"] == ["win", "place", "wide"]
    assert payload["shadow_only_bet_types"] == ["quinella", "trio"]
    assert payload["disabled_bet_types"] == ["exacta", "trifecta"]
    assert payload["gates"]["evidence_gate"]["passed"] is True
    assert payload["gates"]["metric_gate"]["passed"] is True
