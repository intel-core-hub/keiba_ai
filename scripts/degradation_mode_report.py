from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.survival.degradation_mode import DegradationMode, evaluate_degradation


MODES = [mode.value for mode in DegradationMode]


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else event


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _recommendation(*, critical_count: int, danger_count: int, warning_count: int, force_no_bet_count: int) -> str:
    if critical_count > 0 or force_no_bet_count > 0:
        return "halt"
    if danger_count > 0:
        return "restrict"
    if warning_count > 0:
        return "monitor"
    return "healthy"


def build_report(
    *,
    decision_log: Path,
    readiness_gate: Path | None = None,
    bet_type_metrics: Path | None = None,
    latency: Path | None = None,
    output_json: Path | None = None,
    output_csv: Path | None = None,
) -> dict[str, Any]:
    events = _read_jsonl(decision_log)
    readiness = _load_json(readiness_gate)
    metrics = _load_json(bet_type_metrics)
    latency_payload = _load_json(latency)

    mode_counts = Counter({mode: 0 for mode in MODES})
    reason_counts: Counter[str] = Counter()
    excluded_bet_types: Counter[str] = Counter()
    force_no_bet_count = 0
    stake_reduced_count = 0
    coverage_reduced_count = 0
    sequence: list[str] = []

    for event in events:
        payload = _payload(event)
        mode = str(payload.get("degradation_mode") or "")
        if mode not in mode_counts:
            continue
        mode_counts[mode] += 1
        sequence.append(mode)
        reasons = _list_value(payload.get("degradation_reasons"))
        reason_counts.update(reasons)
        if _bool(payload.get("degradation_force_no_bet")):
            force_no_bet_count += 1
        multiplier = float(payload.get("degradation_stake_multiplier") or 1.0)
        if multiplier < 1.0:
            stake_reduced_count += 1
        if mode in {"WARNING", "DANGER", "CRITICAL"}:
            coverage_reduced_count += 1
        reason = str(payload.get("reason") or payload.get("skip_reason") or "")
        if reason.startswith("degradation_"):
            excluded_bet_types[str(payload.get("bet_type") or "unknown")] += 1

    if not events and latency_payload:
        decision = evaluate_degradation(
            {
                "data_quality_score": 1.0,
                "missing_odds_rate": 0.0,
                "stale_odds_rate": 0.0,
                "missing_features_rate": 0.0,
                "loss_streak": 0,
                "drawdown_pct": 0.0,
                "latency_p99_ms": latency_payload.get("p99", 0.0),
                "latency_regression_rate": latency_payload.get("latency_regression_rate", 0.0),
                "drift_gap50": 0.0,
                "feature_psi_max": 0.0,
                "odds_distribution_psi": 0.0,
                "timeout_rate": latency_payload.get("timeout_rate", 0.0),
            }
        )
        mode_counts[decision.mode] += 1
        sequence.append(decision.mode)
        reason_counts.update(decision.reasons)
        force_no_bet_count += int(decision.force_no_bet)

    total = sum(mode_counts.values())
    critical_count = int(mode_counts["CRITICAL"])
    danger_count = int(mode_counts["DANGER"])
    warning_count = int(mode_counts["WARNING"])
    shadow_only_violation_count = int(metrics.get("shadow_only_violation_count", 0) or 0)
    disabled_bet_type_candidate_count = int(metrics.get("disabled_bet_type_candidate_count", 0) or 0)
    max_consecutive_critical = _max_consecutive(sequence, "CRITICAL")
    recommendation = _recommendation(
        critical_count=critical_count,
        danger_count=danger_count,
        warning_count=warning_count,
        force_no_bet_count=force_no_bet_count,
    )

    payload = {
        "schema_version": "degradation_mode_report_v1",
        "decision_log_path": str(decision_log),
        "readiness_gate_path": str(readiness_gate) if readiness_gate else None,
        "bet_type_metrics_path": str(bet_type_metrics) if bet_type_metrics else None,
        "latency_path": str(latency) if latency else None,
        "mode_counts": dict(mode_counts),
        "mode_rates": {mode: (mode_counts[mode] / total if total else 0.0) for mode in MODES},
        "degradation_mode_observed": total > 0,
        "degradation_critical_count": critical_count,
        "degradation_force_no_bet_count": force_no_bet_count,
        "degradation_restrict_count": danger_count + critical_count,
        "degradation_warning_rate": mode_counts["WARNING"] / total if total else 0.0,
        "degradation_danger_rate": mode_counts["DANGER"] / total if total else 0.0,
        "max_consecutive_critical": max_consecutive_critical,
        "reason_counts": dict(reason_counts),
        "excluded_bet_type_counts": dict(excluded_bet_types),
        "stake_reduced_count": stake_reduced_count,
        "coverage_reduced_count": coverage_reduced_count,
        "shadow_only_violation_count": shadow_only_violation_count,
        "disabled_bet_type_candidate_count": disabled_bet_type_candidate_count,
        "readiness_passed": readiness.get("passed"),
        "recommendation": recommendation,
    }

    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if output_csv is not None:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with output_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["metric", "value"])
            writer.writeheader()
            for key in (
                "degradation_critical_count",
                "degradation_force_no_bet_count",
                "degradation_restrict_count",
                "degradation_warning_rate",
                "degradation_danger_rate",
                "stake_reduced_count",
                "coverage_reduced_count",
                "shadow_only_violation_count",
                "disabled_bet_type_candidate_count",
                "recommendation",
            ):
                writer.writerow({"metric": key, "value": payload.get(key)})
    return payload


def _max_consecutive(values: list[str], target: str) -> int:
    best = 0
    current = 0
    for value in values:
        if value == target:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate degradation mode Stage 4 report")
    parser.add_argument("--decision-log", default="logs/decisions.jsonl")
    parser.add_argument("--readiness-gate", default="reports/stage4/readiness_gate.json")
    parser.add_argument("--bet-type-metrics", default="reports/stage4/bet_type_metrics.json")
    parser.add_argument("--latency", default=".ci_latency.json")
    parser.add_argument("--output-json", default="reports/stage4/degradation_mode_report.json")
    parser.add_argument("--output-csv", default="reports/stage4/degradation_mode_report.csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_report(
        decision_log=Path(args.decision_log),
        readiness_gate=Path(args.readiness_gate),
        bet_type_metrics=Path(args.bet_type_metrics),
        latency=Path(args.latency),
        output_json=Path(args.output_json),
        output_csv=Path(args.output_csv),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
