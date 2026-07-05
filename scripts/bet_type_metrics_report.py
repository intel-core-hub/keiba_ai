from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.bet_types import (
    BetTypeConfig,
    BetTypeRegistry,
    default_registry,
    legs_to_json,
    normalize_bet_type,
    normalize_legacy_win_record,
    settle_bet,
)


METRIC_FIELDS = [
    "bet_type",
    "mode",
    "bet_count",
    "opportunity_count",
    "coverage",
    "stake_sum",
    "profit_sum",
    "ROI",
    "Profit Factor",
    "Hit Rate",
    "max_drawdown_contribution",
    "exposure_share",
    "worst_fold_roi",
    "oos_stability",
    "hhi_concentration",
    "recommendation",
    "reason",
]

EXECUTION_EVENT_TYPES = {"BetSubmitted", "BetAccepted", "bet_executed", "bet_accepted"}
CANDIDATE_EVENT_TYPES = EXECUTION_EVENT_TYPES | {"BetRejected", "RaceSettled", "bet_settled"}


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def event_type(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or event.get("event") or "")


def event_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else event


def numeric(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def boolish(value: Any, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "hit", "win"}


def normalize_rows(
    rows: Iterable[dict[str, Any]],
    *,
    registry: BetTypeRegistry,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    normalized_rows: list[dict[str, Any]] = []
    counters = Counter()
    for row in rows:
        missing_bet_type = not row.get("bet_type")
        try:
            normalized = normalize_legacy_win_record(row, registry=registry)
        except ValueError:
            counters["bet_type_missing_count"] += int(missing_bet_type)
            normalized_rows.append({**row, "bet_type": str(row.get("bet_type") or ""), "_normalization_error": True})
            continue

        if missing_bet_type and normalized.get("old_win_compat_converted"):
            counters["old_win_compat_conversion_count"] += 1
        enriched = dict(row)
        enriched.update(
            {
                "bet_type": normalized["bet_type"],
                "legs": legs_to_json(normalized["legs"]),
                "ordered": bool(normalized["ordered"]),
                "shadow_only": bool(normalized["shadow_only"]),
                "production_candidate": bool(normalized["production_candidate"]),
                "max_combinations_per_race": normalized["max_combinations_per_race"],
                "max_race_exposure_share": normalized["max_race_exposure_share"],
                "payout": row.get("payout", normalized.get("payout", "")),
                "payout_per_100": row.get("payout_per_100", normalized.get("payout_per_100", "")),
                "gross_payout": row.get("gross_payout", normalized.get("gross_payout", "")),
            }
        )
        normalized_rows.append(enriched)
    return normalized_rows, dict(counters)


def _mode(config: BetTypeConfig) -> str:
    return config.mode.value


def _profit_for_row(row: dict[str, Any]) -> float:
    if row.get("profit") not in (None, ""):
        return numeric(row.get("profit"))
    hit = boolish(row.get("hit"), default=False)
    stake = numeric(row.get("stake"))
    if hit:
        try:
            if row.get("gross_payout") not in (None, ""):
                return settle_bet(stake, hit=True, gross_payout=numeric(row.get("gross_payout")))
            if row.get("payout_per_100") not in (None, ""):
                return settle_bet(stake, hit=True, payout_per_100=numeric(row.get("payout_per_100")))
            return settle_bet(stake, numeric(row.get("payout")), True)
        except ValueError:
            return 0.0
    return -stake if row.get("hit") not in (None, "") else 0.0


def _profit_factor(profits: list[float]) -> float | None:
    gains = sum(value for value in profits if value > 0)
    losses = abs(sum(value for value in profits if value < 0))
    if losses == 0:
        if gains > 0:
            return math.inf
        return None
    return gains / losses


def _max_drawdown(profits: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _hhi(rows: list[dict[str, Any]]) -> float:
    by_race: dict[str, float] = defaultdict(float)
    for row in rows:
        by_race[str(row.get("race_id") or "")] += numeric(row.get("stake"))
    total = sum(by_race.values())
    if total <= 0:
        return 0.0
    return sum((value / total) ** 2 for value in by_race.values())


def _worst_fold_roi(rows: list[dict[str, Any]]) -> float | None:
    by_fold: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        fold = str(row.get("fold") or row.get("date") or row.get("race_date") or (index // 10))
        by_fold[fold].append(row)
    values = []
    for fold_rows in by_fold.values():
        stake = sum(numeric(row.get("stake")) for row in fold_rows)
        if stake <= 0:
            continue
        profit = sum(_profit_for_row(row) for row in fold_rows)
        values.append(profit / stake)
    return min(values) if values else None


def _oos_stability(rows: list[dict[str, Any]]) -> float | None:
    by_fold: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        fold = str(row.get("fold") or row.get("date") or row.get("race_date") or (index // 10))
        by_fold[fold].append(row)
    rois = []
    for fold_rows in by_fold.values():
        stake = sum(numeric(row.get("stake")) for row in fold_rows)
        if stake > 0:
            rois.append(sum(_profit_for_row(row) for row in fold_rows) / stake)
    if len(rois) < 2:
        return None
    mean = sum(rois) / len(rois)
    variance = sum((value - mean) ** 2 for value in rois) / len(rois)
    return math.sqrt(variance)


def _recommendation(
    *,
    config: BetTypeConfig,
    roi: float | None,
    profit_factor: float | None,
    coverage: float,
    max_drawdown_contribution: float,
    hhi: float,
    oos_stability: float | None,
    risk_reject_rate: float,
) -> tuple[str, str]:
    if not config.enabled:
        return "disabled", config.reason or "disabled bet_type"
    if config.production_candidate:
        if coverage < 0.01 or coverage > 0.50:
            return "limit_or_review", "production candidate coverage is outside v2.3 normal range"
        if roi is not None and roi < -0.05:
            return "limit_or_review", "production candidate ROI is below bet_type C threshold"
        return "production_candidate", "eligible subject to A2/A3/A7 review"

    reasons: list[str] = []
    if roi is not None and roi < (config.disable_if_roi_below if config.disable_if_roi_below is not None else -0.05):
        reasons.append("ROI < -5%")
    if profit_factor is not None and profit_factor < (
        config.disable_if_profit_factor_below if config.disable_if_profit_factor_below is not None else 0.95
    ):
        reasons.append("Profit Factor < 0.95")
    if config.disable_if_dd_contribution_above is not None and max_drawdown_contribution > config.disable_if_dd_contribution_above:
        reasons.append("max_drawdown_contribution above threshold")
    if coverage < 0.01 or coverage > 0.50:
        reasons.append("Coverage outside 1%-50%")
    if hhi >= 0.60:
        reasons.append("HHI >= 0.60")
    if risk_reject_rate >= 0.20:
        reasons.append("RiskClamp rejection frequent")
    if reasons:
        return "disable", "; ".join(reasons)

    oos_ok = oos_stability is None or oos_stability < 0.15
    if (
        roi is not None
        and roi >= 0
        and profit_factor is not None
        and profit_factor >= 1.05
        and 0.01 <= coverage <= 0.50
        and max_drawdown_contribution <= (config.disable_if_dd_contribution_above or 1.0)
        and oos_ok
    ):
        return "promote_candidate_possible", "requires additional Shadow and manual review"
    return "keep_shadow", "sample is not clearly superior but not yet dangerous"


def _decision_opportunities(
    events: list[dict[str, Any]],
    *,
    registry: BetTypeRegistry,
) -> tuple[Counter, dict[str, int]]:
    opportunities: Counter = Counter()
    counters = Counter()
    for event in events:
        etype = event_type(event)
        if etype not in CANDIDATE_EVENT_TYPES | {"BetTypeExecutionRejected"}:
            continue
        payload = event_payload(event)
        missing_bet_type = not payload.get("bet_type")
        try:
            normalized = normalize_legacy_win_record(payload, registry=registry)
        except ValueError:
            if missing_bet_type:
                counters["bet_type_missing_count"] += 1
            elif etype in EXECUTION_EVENT_TYPES | {"BetTypeExecutionRejected"}:
                counters["production_execution_unknown_bet_type_count"] += 1
            continue
        if missing_bet_type and normalized.get("old_win_compat_converted"):
            counters["old_win_compat_conversion_count"] += 1
        opportunities[normalized["bet_type"]] += 1
    return opportunities, dict(counters)


def _violation_counts(
    *,
    rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
    registry: BetTypeRegistry,
) -> dict[str, int]:
    shadow_only_violation_count = 0
    disabled_bet_type_candidate_count = 0
    unknown_execution_count = 0

    for row in rows:
        bet_type = str(row.get("bet_type") or "")
        try:
            config = registry.get(bet_type)
        except ValueError:
            continue
        if not config.enabled:
            disabled_bet_type_candidate_count += 1

    for event in events:
        etype = event_type(event)
        payload = event_payload(event)
        reason = str(payload.get("reason") or "")
        try:
            normalized = normalize_legacy_win_record(payload, registry=registry)
            config = registry.get(normalized["bet_type"])
        except ValueError:
            if etype in EXECUTION_EVENT_TYPES | {"BetTypeExecutionRejected"}:
                unknown_execution_count += 1
            continue
        if not config.enabled and etype in CANDIDATE_EVENT_TYPES:
            disabled_bet_type_candidate_count += 1
        if config.shadow_only and (
            etype in EXECUTION_EVENT_TYPES
            or reason == "shadow_only_execution_rejected"
            or str(payload.get("execution_status") or "").upper() in {"LIVE", "SUBMITTED", "BLOCKED"}
        ):
            shadow_only_violation_count += 1
        if etype in EXECUTION_EVENT_TYPES and not config.production_candidate:
            shadow_only_violation_count += int(config.shadow_only)
    return {
        "shadow_only_violation_count": shadow_only_violation_count,
        "disabled_bet_type_candidate_count": disabled_bet_type_candidate_count,
        "production_execution_unknown_bet_type_count": unknown_execution_count,
    }


def build_report(
    *,
    derived_bets: Path,
    decisions_jsonl: Path,
    readiness_gate: Path | None = None,
    output_json: Path | None = None,
    output_csv: Path | None = None,
    registry: BetTypeRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or default_registry()
    derived_raw = read_csv_rows(derived_bets)
    decisions = read_jsonl(decisions_jsonl)
    rows, row_counters = normalize_rows(derived_raw, registry=registry)
    opportunities, event_counters = _decision_opportunities(decisions, registry=registry)

    if not opportunities:
        opportunities = Counter(row.get("bet_type") for row in rows if row.get("bet_type"))

    total_stake = sum(numeric(row.get("stake")) for row in rows)
    total_drawdown = sum(_max_drawdown([_profit_for_row(row) for row in rows_by_type]) for rows_by_type in _group_by_bet_type(rows).values())
    bet_type_metrics: list[dict[str, Any]] = []

    for bet_type, config in registry.all().items():
        bet_rows = [row for row in rows if row.get("bet_type") == bet_type]
        stake_sum = sum(numeric(row.get("stake")) for row in bet_rows)
        profits = [_profit_for_row(row) for row in bet_rows]
        profit_sum = sum(profits)
        hit_rows = [row for row in bet_rows if row.get("hit") not in (None, "")]
        hit_count = sum(1 for row in hit_rows if boolish(row.get("hit")))
        bet_count = len(bet_rows)
        opportunity_count = int(opportunities.get(bet_type, bet_count))
        coverage = (bet_count / opportunity_count) if opportunity_count > 0 else 0.0
        roi = (profit_sum / stake_sum) if stake_sum > 0 else None
        pf = _profit_factor(profits)
        max_dd = _max_drawdown(profits)
        max_dd_contribution = (max_dd / total_drawdown) if total_drawdown > 0 else 0.0
        exposure_share = (stake_sum / total_stake) if total_stake > 0 else 0.0
        hhi = _hhi(bet_rows)
        worst_fold_roi = _worst_fold_roi(bet_rows)
        oos_stability = _oos_stability(bet_rows)
        risk_rejections = sum(
            1
            for row in bet_rows
            if "risk" in str(row.get("risk_clamp_reason") or row.get("reason") or "").lower()
            and "allowed" not in str(row.get("risk_clamp_reason") or row.get("reason") or "").lower()
        )
        risk_reject_rate = risk_rejections / max(opportunity_count, 1)
        recommendation, reason = _recommendation(
            config=config,
            roi=roi,
            profit_factor=pf,
            coverage=coverage,
            max_drawdown_contribution=max_dd_contribution,
            hhi=hhi,
            oos_stability=oos_stability,
            risk_reject_rate=risk_reject_rate,
        )
        bet_type_metrics.append(
            {
                "bet_type": bet_type,
                "mode": _mode(config),
                "bet_count": bet_count,
                "opportunity_count": opportunity_count,
                "coverage": _round(coverage),
                "stake_sum": _round(stake_sum),
                "profit_sum": _round(profit_sum),
                "ROI": _round_or_none(roi),
                "Profit Factor": _round_or_inf(pf),
                "Hit Rate": _round(hit_count / len(hit_rows)) if hit_rows else None,
                "max_drawdown_contribution": _round(max_dd_contribution),
                "exposure_share": _round(exposure_share),
                "worst_fold_roi": _round_or_none(worst_fold_roi),
                "oos_stability": _round_or_none(oos_stability),
                "hhi_concentration": _round(hhi),
                "recommendation": recommendation,
                "reason": reason,
            }
        )

    counters = Counter(row_counters)
    counters.update(event_counters)
    counters.update(_violation_counts(rows=rows, events=decisions, registry=registry))
    summary = {
        "production_candidate_bet_types": registry.production_candidate_bet_types(),
        "shadow_only_bet_types": registry.shadow_only_bet_types(),
        "disabled_bet_types": registry.disabled_bet_types(),
        "shadow_only_violation_count": int(counters.get("shadow_only_violation_count", 0)),
        "disabled_bet_type_candidate_count": int(counters.get("disabled_bet_type_candidate_count", 0)),
        "production_execution_unknown_bet_type_count": int(counters.get("production_execution_unknown_bet_type_count", 0)),
        "bet_type_missing_count": int(counters.get("bet_type_missing_count", 0)),
        "old_win_compat_conversion_count": int(counters.get("old_win_compat_conversion_count", 0)),
    }

    payload = {
        "schema_version": "bet_type_metrics_v1",
        "derived_bets_path": str(derived_bets),
        "decisions_jsonl_path": str(decisions_jsonl),
        "readiness_gate_path": str(readiness_gate) if readiness_gate else None,
        "bet_type_metrics": bet_type_metrics,
        "summary": summary,
        **summary,
    }

    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if output_csv is not None:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with output_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=METRIC_FIELDS)
            writer.writeheader()
            writer.writerows({field: row.get(field, "") for field in METRIC_FIELDS} for row in bet_type_metrics)
    return payload


def _group_by_bet_type(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("bet_type") or "")].append(row)
    return grouped


def _round(value: float) -> float:
    return round(float(value), 6)


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else _round(value)


def _round_or_inf(value: float | None) -> float | str | None:
    if value is None:
        return None
    if math.isinf(value):
        return "inf"
    return _round(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Stage 4 bet_type metrics report")
    parser.add_argument("--derived-bets", default="derived/bets.csv")
    parser.add_argument("--decisions-jsonl", default="logs/decisions.jsonl")
    parser.add_argument("--readiness-gate", default="reports/stage4/readiness_gate.json")
    parser.add_argument("--output-json", default="reports/stage4/bet_type_metrics.json")
    parser.add_argument("--output-csv", default="reports/stage4/bet_type_metrics.csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_report(
        derived_bets=Path(args.derived_bets),
        decisions_jsonl=Path(args.decisions_jsonl),
        readiness_gate=Path(args.readiness_gate) if args.readiness_gate else None,
        output_json=Path(args.output_json),
        output_csv=Path(args.output_csv),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
