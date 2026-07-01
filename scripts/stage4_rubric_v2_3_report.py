from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.bet_types import default_registry


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_summary() -> dict[str, Any]:
    registry = default_registry()
    return {
        "production_candidate_bet_types": registry.production_candidate_bet_types(),
        "shadow_only_bet_types": registry.shadow_only_bet_types(),
        "disabled_bet_types": registry.disabled_bet_types(),
    }


def evaluate_bet_type_gate(metrics_path: Path) -> dict[str, Any]:
    expected = _expected_summary()
    if not metrics_path.exists():
        return {
            "evidence_gate": {
                "passed": False,
                "failures": ["bet_type_metrics_missing"],
            },
            "metric_gate": {"passed": True, "failures": []},
            "details": {
                "bet_type_metrics_path": str(metrics_path),
                **expected,
                "shadow_only_violation_count": 0,
                "disabled_bet_type_candidate_count": 0,
                "production_execution_unknown_bet_type_count": 0,
                "bet_type_missing_count": 0,
                "old_win_compat_conversion_count": 0,
            },
        }

    payload = _load_json(metrics_path)
    metrics = payload.get("bet_type_metrics")
    evidence_failures: list[str] = []
    metric_failures: list[str] = []
    if not isinstance(metrics, list) or not metrics:
        evidence_failures.append("bet_type_metrics_not_computable")

    details = {
        "bet_type_metrics_path": str(metrics_path),
        **expected,
        "shadow_only_violation_count": int(payload.get("shadow_only_violation_count", 0) or 0),
        "disabled_bet_type_candidate_count": int(payload.get("disabled_bet_type_candidate_count", 0) or 0),
        "production_execution_unknown_bet_type_count": int(payload.get("production_execution_unknown_bet_type_count", 0) or 0),
        "bet_type_missing_count": int(payload.get("bet_type_missing_count", 0) or 0),
        "old_win_compat_conversion_count": int(payload.get("old_win_compat_conversion_count", 0) or 0),
    }

    for key, expected_value in expected.items():
        actual_value = list(payload.get(key) or [])
        if actual_value != expected_value:
            metric_failures.append(f"{key}_mismatch")

    if details["bet_type_missing_count"] > 0:
        evidence_failures.append("bet_type_missing_unconvertible")
    if details["shadow_only_violation_count"] > 0:
        metric_failures.append("shadow_only_violation_count")
    if details["disabled_bet_type_candidate_count"] > 0:
        metric_failures.append("disabled_bet_type_candidate_count")
    if details["production_execution_unknown_bet_type_count"] > 0:
        metric_failures.append("production_execution_unknown_bet_type_count")

    return {
        "evidence_gate": {"passed": not evidence_failures, "failures": evidence_failures},
        "metric_gate": {"passed": not metric_failures, "failures": metric_failures},
        "details": details,
    }


def build_report(
    *,
    readiness_path: Path,
    bet_type_metrics_path: Path,
    degradation_report_path: Path = Path("reports/stage4/degradation_mode_report.json"),
    output_json: Path,
    output_md: Path,
) -> dict[str, Any]:
    readiness = _load_json(readiness_path)
    degradation = _load_json(degradation_report_path)
    bet_type_gate = evaluate_bet_type_gate(bet_type_metrics_path)
    readiness_evidence = readiness.get("evidence_gate", {}) if isinstance(readiness.get("evidence_gate"), dict) else {}
    readiness_metric = readiness.get("metric_gate", {}) if isinstance(readiness.get("metric_gate"), dict) else {}
    evidence_passed = bool(readiness_evidence.get("passed", True)) and bet_type_gate["evidence_gate"]["passed"]
    degradation_metric_failures: list[str] = []
    degradation_critical_count = int(degradation.get("degradation_critical_count", 0) or 0)
    degradation_force_no_bet_count = int(degradation.get("degradation_force_no_bet_count", 0) or 0)
    if int(degradation.get("max_consecutive_critical", 0) or 0) >= 2:
        degradation_metric_failures.append("critical_degradation_continuous")
    if degradation_force_no_bet_count >= 3:
        degradation_metric_failures.append("force_no_bet_persistent")
    metric_passed = bool(readiness_metric.get("passed", True)) and bet_type_gate["metric_gate"]["passed"] and not degradation_metric_failures
    final_rank = "C" if not evidence_passed or not metric_passed else None
    reason = (
        "Evidence Gate not passed under v2.3."
        if not evidence_passed
        else "Metric Gate failed under v2.3."
        if not metric_passed
        else "Gate-level blockers are clear; weighted score still requires A1-A7 inputs."
    )

    details = bet_type_gate["details"]
    payload = {
        "rubric_version": "v2.3",
        "evaluation_basis": "reports/stage4 artifact bundle with bet_type_metrics",
        "stage4_verdict": "PASS" if evidence_passed and metric_passed else "C",
        "final_stage4_rank": final_rank or "PENDING_WEIGHTED_SCORE",
        "release_recommendation": "NOT_RELEASE_READY" if final_rank == "C" else "PENDING_WEIGHTED_SCORE",
        "gates": {
            "evidence_gate": {
                "passed": evidence_passed,
                "failures": list(readiness_evidence.get("failures", [])) + bet_type_gate["evidence_gate"]["failures"],
            },
            "metric_gate": {
                "passed": metric_passed,
                "failures": list(readiness_metric.get("failures", [])) + bet_type_gate["metric_gate"]["failures"] + degradation_metric_failures,
            },
            "bet_type_gate": bet_type_gate,
        },
        "final_rank": {"rank": final_rank, "reason": reason},
        "score": {
            "computable": False,
            "reason": "v2.3 Bet Type Gate is evaluated; weighted FinalScore still requires complete A1-A7 evidence.",
        },
        "source_artifacts": {
            "readiness_gate": str(readiness_path),
            "bet_type_metrics": str(bet_type_metrics_path),
            "degradation_report": str(degradation_report_path),
        },
        "degradation_mode_observed": bool(degradation.get("degradation_mode_observed", False)),
        "degradation_critical_count": degradation_critical_count,
        "degradation_force_no_bet_count": degradation_force_no_bet_count,
        "degradation_warning_rate": float(degradation.get("degradation_warning_rate", 0.0) or 0.0),
        "degradation_danger_rate": float(degradation.get("degradation_danger_rate", 0.0) or 0.0),
        "degradation_recommendation": degradation.get("recommendation", "healthy"),
        **details,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(_markdown(payload), encoding="utf-8")
    return payload


def _markdown(payload: dict[str, Any]) -> str:
    gates = payload.get("gates", {})
    details = gates.get("bet_type_gate", {}).get("details", {})
    lines = [
        "# Stage 4 Rubric v2.3 Compliance",
        "",
        f"- final_rank: {payload.get('final_rank', {}).get('rank')}",
        f"- reason: {payload.get('final_rank', {}).get('reason')}",
        f"- bet_type_metrics_path: {details.get('bet_type_metrics_path')}",
        f"- degradation_recommendation: {payload.get('degradation_recommendation')}",
        "",
        "## Bet Type Gate",
        "",
        f"- production_candidate_bet_types: {details.get('production_candidate_bet_types')}",
        f"- shadow_only_bet_types: {details.get('shadow_only_bet_types')}",
        f"- disabled_bet_types: {details.get('disabled_bet_types')}",
        f"- shadow_only_violation_count: {details.get('shadow_only_violation_count')}",
        f"- disabled_bet_type_candidate_count: {details.get('disabled_bet_type_candidate_count')}",
        f"- production_execution_unknown_bet_type_count: {details.get('production_execution_unknown_bet_type_count')}",
        f"- bet_type_missing_count: {details.get('bet_type_missing_count')}",
        f"- old_win_compat_conversion_count: {details.get('old_win_compat_conversion_count')}",
        "",
        "## Gates",
        "",
        f"- Evidence Gate: {'PASS' if gates.get('evidence_gate', {}).get('passed') else 'FAIL'}",
        f"- Metric Gate: {'PASS' if gates.get('metric_gate', {}).get('passed') else 'FAIL'}",
        "",
        "## Degradation Mode",
        "",
        f"- observed: {payload.get('degradation_mode_observed')}",
        f"- critical_count: {payload.get('degradation_critical_count')}",
        f"- force_no_bet_count: {payload.get('degradation_force_no_bet_count')}",
        f"- warning_rate: {payload.get('degradation_warning_rate')}",
        f"- danger_rate: {payload.get('degradation_danger_rate')}",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Stage 4 rubric v2.3 compliance report")
    parser.add_argument("--readiness", default="reports/stage4/readiness_gate.json")
    parser.add_argument("--bet-type-metrics", default="reports/stage4/bet_type_metrics.json")
    parser.add_argument("--degradation-report", default="reports/stage4/degradation_mode_report.json")
    parser.add_argument("--output-json", default="reports/stage4/rubric_v2_3_compliance.json")
    parser.add_argument("--output-md", default="reports/stage4/rubric_v2_3_compliance.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_report(
        readiness_path=Path(args.readiness),
        bet_type_metrics_path=Path(args.bet_type_metrics),
        degradation_report_path=Path(args.degradation_report),
        output_json=Path(args.output_json),
        output_md=Path(args.output_md),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["gates"]["evidence_gate"]["passed"] and payload["gates"]["metric_gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
