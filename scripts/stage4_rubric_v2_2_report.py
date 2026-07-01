from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


GRADE_ORDER = ("S", "A", "B", "C")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _min_grade(*grades: str) -> str:
    valid = [grade for grade in grades if grade in GRADE_ORDER]
    if not valid:
        return "C"
    return max(valid, key=GRADE_ORDER.index)


def _less_is_better(value: float | None, *, s: float, a: float, b: float) -> str:
    if value is None:
        return "C"
    if value < s:
        return "S"
    if value < a:
        return "A"
    if value < b:
        return "B"
    return "C"


def _equals_zero(value: float | None) -> str:
    if value is None:
        return "C"
    return "S" if value == 0 else "C"


def _grade_a4(latency: dict[str, Any]) -> dict[str, Any]:
    p50 = _as_float(latency.get("p50"))
    p95 = _as_float(latency.get("p95"))
    p99 = _as_float(latency.get("p99"))
    p999 = _as_float(latency.get("p999"))
    timeout_rate = _as_float(latency.get("timeout_rate"))
    baseline_p99 = _as_float(latency.get("baseline_p99"))
    regression = _as_float(latency.get("latency_regression_rate"))
    if regression is None and p99 is not None and baseline_p99 not in (None, 0):
        regression = (p99 / baseline_p99) - 1.0
    ratio = None if p50 in (None, 0) or p99 is None else p99 / p50

    grades = {
        "p50_latency": _less_is_better(p50, s=10.0, a=20.0, b=40.0),
        "p95_latency": _less_is_better(p95, s=30.0, a=50.0, b=80.0),
        "p99_latency": _less_is_better(p99, s=50.0, a=100.0, b=200.0),
        "p999_latency": _less_is_better(p999, s=120.0, a=250.0, b=400.0),
        "timeout_rate": _equals_zero(timeout_rate),
        "p99_over_p50_ratio": _less_is_better(ratio, s=5.0, a=10.0, b=15.0),
        "latency_regression_rate": (
            _less_is_better(regression, s=0.05, a=0.15, b=0.30) if regression is not None else None
        ),
    }
    return {
        "status": "EVALUATED",
        "grade": _min_grade(*grades.values()),
        "metrics": {
            "p50": p50,
            "p95": p95,
            "p99": p99,
            "p999": p999,
            "timeout_rate": timeout_rate,
            "p99_over_p50_ratio": round(ratio, 4) if ratio is not None else None,
            "baseline_p99": baseline_p99,
            "latency_regression_rate": round(regression, 6) if regression is not None else None,
        },
        "subgrades": grades,
    }


def _grade_a5(readiness: dict[str, Any]) -> dict[str, Any]:
    checks = readiness.get("checks", {}) if isinstance(readiness.get("checks"), dict) else {}
    details = {
        "audit_hash_chain": bool(checks.get("event_chain", {}).get("passed")),
        "replay_deterministic_match": bool(checks.get("replay", {}).get("passed")),
        "required_hash_fields": bool(checks.get("payload_hashes", {}).get("passed")),
        "audit_envelopes": bool(checks.get("audit_envelopes", {}).get("passed")),
    }
    passed = all(details.values())
    return {
        "status": "EVALUATED",
        "grade": "PASS" if passed else "FAIL",
        "details": details,
        "note": "A5 in rubric v2.2 is primarily pass/fail; no S/A/B thresholds are defined in the artifact set.",
    }


def _grade_a6(readiness: dict[str, Any]) -> dict[str, Any]:
    checks = readiness.get("checks", {}) if isinstance(readiness.get("checks"), dict) else {}
    coverage = checks.get("critical_path_coverage", {})
    governance = checks.get("governance_lint", {})
    branch_pct = _as_float(coverage.get("branch_coverage_pct"))
    if branch_pct is None:
        coverage_grade = "C"
    elif branch_pct >= 90.0:
        coverage_grade = "S"
    elif branch_pct >= 85.0:
        coverage_grade = "A"
    elif branch_pct >= 80.0:
        coverage_grade = "B"
    else:
        coverage_grade = "C"
    governance_passed = bool(governance.get("passed"))
    overall = coverage_grade if governance_passed else "C"
    return {
        "status": "EVALUATED",
        "grade": overall,
        "details": {
            "critical_path_branch_coverage": branch_pct,
            "critical_path_branch_coverage_grade": coverage_grade,
            "governance_lint_passed": governance_passed,
            "metric_gate_passed": bool(readiness.get("metric_gate", {}).get("passed")),
        },
    }


def _grade_a7_3(drift: dict[str, Any], drift_exists: bool) -> dict[str, Any]:
    if not drift_exists:
        return {
            "status": "NOT_EVALUABLE",
            "grade": None,
            "reason": "feature_drift_report.json missing",
        }

    psi = drift.get("psi", {}) if isinstance(drift.get("psi"), dict) else {}
    gap50 = _as_float(drift.get("gap50"))
    over_a = [name for name, value in psi.items() if _as_float(value) is not None and float(value) >= 0.20]
    valid_values = [_as_float(value) for value in psi.values()]
    valid_values = [value for value in valid_values if value is not None]

    if gap50 is None:
        grade = "B" if over_a else "A"
        note = "Gap50 metric is not present in the current artifact; PSI-only upper bound used."
    elif gap50 >= 0.04 or len(over_a) >= 2:
        grade = "C"
        note = "Gap50 or multiple PSI breaches exceeded the rubric threshold."
    elif over_a:
        grade = "B"
        note = "At least one PSI value exceeded the A threshold."
    elif gap50 < 0.01 and valid_values and max(valid_values) < 0.10:
        grade = "S"
        note = "Gap50 and PSI both satisfy the S threshold."
    else:
        grade = "A"
        note = "Gap50 and PSI satisfy the A threshold."

    return {
        "status": "PARTIAL" if gap50 is None else "EVALUATED",
        "grade": grade,
        "details": {
            "gap50": gap50,
            "max_psi": _as_float(drift.get("max_psi")),
            "psi_over_threshold": over_a,
            "top_features": drift.get("top_features", []),
        },
        "note": note,
    }


def _blocked_axis(reason: str) -> dict[str, Any]:
    return {"status": "NOT_EVALUABLE", "grade": None, "reason": reason}


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _final_rank(readiness: dict[str, Any]) -> dict[str, Any]:
    evidence_passed = bool(readiness.get("evidence_gate", {}).get("passed"))
    metric_passed = bool(readiness.get("metric_gate", {}).get("passed"))
    if not evidence_passed:
        return {
            "rank": "C",
            "reason": "Evidence Gate not passed; rubric v2.2 treats this as evaluation not established / 投入不可.",
        }
    if not metric_passed:
        return {
            "rank": "C",
            "reason": "Metric Gate failed; rubric v2.2 forces an immediate C.",
        }
    return {
        "rank": None,
        "reason": "Gate-level blockers are cleared, but A1/A2/A3/A7 score inputs are still incomplete so FinalScore is not computed here.",
    }


def build_report(
    *,
    readiness_path: Path,
    survivability_path: Path,
    latency_path: Path,
    drift_path: Path,
    output_json: Path,
    output_md: Path,
) -> dict[str, Any]:
    readiness = _load_json(readiness_path)
    survivability = _load_json(survivability_path)
    latency = _load_json(latency_path)
    drift_exists = drift_path.exists()
    drift = _load_json(drift_path) if drift_exists else {}

    axes = {
        "A1": _blocked_axis("Prediction quality artifacts are not summarized into rubric-ready score inputs in the current evidence bundle."),
        "A2": _blocked_axis("Walk-forward fold and realized PnL evidence required for rubric scoring is not present in the current report set."),
        "A3": _blocked_axis("Risk survivability score inputs such as drawdown, ruin probability, and recovery time are not bundled in the current report set."),
        "A4": _grade_a4(latency),
        "A5": _grade_a5(readiness),
        "A6": _grade_a6(readiness),
        "A7": {
            "status": "PARTIAL",
            "grade": None,
            "subaxes": {
                "A7_1_regime": _blocked_axis("Regime-specific rubric grading is not bundled as a dedicated artifact."),
                "A7_2_oos_stability": _blocked_axis("Fold-level variance artifact is not available in the current report set."),
                "A7_3_drift": _grade_a7_3(drift, drift_exists),
                "A7_4_coverage": _blocked_axis("Live bet-rate coverage artifact is not available in the current report set."),
                "A7_5_concentration": _blocked_axis("Concentration / HHI artifact is not available in the current report set."),
            },
            "note": "A7 remains incomplete until the missing robustness artifacts are generated from real operating data.",
        },
    }

    final_rank = _final_rank(readiness)
    payload = {
        "rubric_version": "v2.2",
        "evaluation_basis": "reports/stage4 artifact bundle",
        "stage4_verdict": readiness.get("stage4_verdict"),
        "gates": {
            "evidence_gate": readiness.get("evidence_gate", {}),
            "metric_gate": readiness.get("metric_gate", {}),
        },
        "final_rank": final_rank,
        "score": {
            "computable": False,
            "reason": "A1/A2/A3/A7 inputs are incomplete, so the weighted FinalScore is intentionally not computed.",
        },
        "axes": axes,
        "remaining_blockers": list(readiness.get("blocking_reasons", [])),
        "source_artifacts": {
            "readiness_gate": str(readiness_path),
            "survivability": str(survivability_path),
            "latency": str(latency_path),
            "feature_drift": str(drift_path) if drift_exists else None,
        },
        "current_stage": survivability.get("stage"),
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(_markdown(payload), encoding="utf-8")
    return payload


def _markdown(payload: dict[str, Any]) -> str:
    gate_rows = "\n".join(
        f"| {name} | {'PASS' if data.get('passed') else 'FAIL'} | {data.get('failures', [])} |"
        for name, data in payload.get("gates", {}).items()
    )
    a7_rows = "\n".join(
        f"| {name} | {data.get('status')} | {data.get('grade')} | {data.get('reason', data.get('note', ''))} |"
        for name, data in payload.get("axes", {}).get("A7", {}).get("subaxes", {}).items()
    )
    blockers = "\n".join(f"- {item}" for item in payload.get("remaining_blockers", [])) or "- none"
    axes = payload.get("axes", {})
    lines = [
        "# Stage 4 Rubric v2.2 Compliance",
        "",
        f"- stage4_verdict: {payload.get('stage4_verdict')}",
        f"- final_rank: {payload.get('final_rank', {}).get('rank')}",
        f"- reason: {payload.get('final_rank', {}).get('reason')}",
        f"- current_stage: {payload.get('current_stage')}",
        "",
        "## Gates",
        "",
        "| Gate | Status | Failures |",
        "|---|---|---|",
        gate_rows,
        "",
        "## Evaluated Axes",
        "",
        f"- A4 latency: {axes.get('A4', {}).get('grade')}",
        f"- A5 audit/replay: {axes.get('A5', {}).get('grade')}",
        f"- A6 governance/coverage: {axes.get('A6', {}).get('grade')}",
        "",
        "## A7 Subaxes",
        "",
        "| Subaxis | Status | Grade | Note |",
        "|---|---|---|---|",
        a7_rows,
        "",
        "## Remaining Blockers",
        "",
        blockers,
        "",
        "## Score",
        "",
        payload.get("score", {}).get("reason", ""),
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Stage 4 rubric v2.2 compliance report")
    parser.add_argument("--readiness", default="reports/stage4/readiness_gate.json")
    parser.add_argument("--survivability", default="reports/stage4/survivability_evaluation_v2.json")
    parser.add_argument("--latency", default=".ci_latency.json")
    parser.add_argument("--feature-drift", default="reports/stage4/feature_drift_report.json")
    parser.add_argument("--output-json", default="reports/stage4/rubric_v2_2_compliance.json")
    parser.add_argument("--output-md", default="reports/stage4/rubric_v2_2_compliance.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_report(
        readiness_path=Path(args.readiness),
        survivability_path=Path(args.survivability),
        latency_path=Path(args.latency),
        drift_path=Path(args.feature_drift),
        output_json=Path(args.output_json),
        output_md=Path(args.output_md),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
