from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _odds_regime(odds: float) -> str:
    if odds <= 0:
        return "UNKNOWN"
    if odds <= 2.0:
        return "FAVORITE_HEAVY"
    if odds <= 4.0:
        return "FAVORITE_TO_BALANCED"
    if odds <= 8.0:
        return "BALANCED"
    if odds <= 20.0:
        return "LONGSHOT"
    return "DEEP_LONGSHOT"


def _max_consecutive_losses(rows: list[dict[str, Any]]) -> int:
    max_loss = 0
    current = 0
    for row in rows:
        if _float(row.get("profit")) < 0:
            current += 1
            max_loss = max(max_loss, current)
        else:
            current = 0
    return max_loss


def _max_drawdown(rows: list[dict[str, Any]]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for row in rows:
        equity += _float(row.get("profit"))
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _shadow_input_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        race_id = str(row.get("race_id") or "").strip()
        selection = str(row.get("selection") or row.get("horse_id") or "").strip()
        features: dict[str, Any] = {}
        raw_features = str(row.get("features") or "").strip()
        if raw_features:
            try:
                features = json.loads(raw_features)
            except json.JSONDecodeError:
                features = {}
        indexed[(race_id, selection)] = {
            **row,
            "features_parsed": features,
            "odds_regime": _odds_regime(_float(row.get("odds"))),
            "favorite_rank": _int(features.get("favorite_rank"), default=0),
            "field_size": _int(features.get("field_size"), default=0),
        }
    return indexed


def evaluate_pre_contract_sandbox(
    *,
    bets_csv: Path,
    shadow_input_csv: Path,
    output_json: Path,
    output_md: Path,
) -> dict[str, Any]:
    bets = _read_csv(bets_csv)
    shadow_rows = _read_csv(shadow_input_csv)
    source_index = _shadow_input_index(shadow_rows)

    enriched: list[dict[str, Any]] = []
    for row in bets:
        race_id = str(row.get("race_id") or "").strip()
        selection = str(row.get("selection") or row.get("selection_id") or "").strip()
        source = source_index.get((race_id, selection), {})
        enriched.append(
            {
                **row,
                "race_id": race_id,
                "selection": selection,
                "stake": _float(row.get("stake")),
                "profit": _float(row.get("profit")),
                "hit": _int(row.get("hit")),
                "odds": _float(row.get("odds") or source.get("odds")),
                "odds_regime": source.get("odds_regime") or _odds_regime(_float(row.get("odds"))),
                "favorite_rank": source.get("favorite_rank", 0),
                "field_size": source.get("field_size", 0),
                "api_status": str(row.get("api_status") or ""),
            }
        )

    stake_sum = sum(row["stake"] for row in enriched)
    profit_sum = sum(row["profit"] for row in enriched)
    roi = profit_sum / stake_sum if stake_sum else None
    hit_sum = sum(row["hit"] for row in enriched)
    race_count = len({row["race_id"] for row in enriched})

    by_regime: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        grouped[str(row["odds_regime"])].append(row)
    for regime, rows in sorted(grouped.items()):
        stake = sum(row["stake"] for row in rows)
        profit = sum(row["profit"] for row in rows)
        by_regime[regime] = {
            "bets": len(rows),
            "stake_sum": stake,
            "profit_sum": profit,
            "roi": profit / stake if stake else None,
            "hit_sum": sum(row["hit"] for row in rows),
        }

    favorite_rank_counter = Counter()
    for row in enriched:
        rank = _int(row.get("favorite_rank"))
        if rank > 0:
            if rank <= 3:
                favorite_rank_counter["top_3"] += 1
            elif rank <= 8:
                favorite_rank_counter["rank_4_to_8"] += 1
            else:
                favorite_rank_counter["rank_9_plus"] += 1
        else:
            favorite_rank_counter["unknown"] += 1

    summary = {
        "passed": True,
        "evidence_eligible": False,
        "bets_csv": str(bets_csv),
        "shadow_input_csv": str(shadow_input_csv),
        "race_count": race_count,
        "candidate_count": len(enriched),
        "stake_sum": stake_sum,
        "profit_sum": profit_sum,
        "roi": roi,
        "hit_sum": hit_sum,
        "hit_rate": hit_sum / len(enriched) if enriched else None,
        "max_consecutive_losses": _max_consecutive_losses(enriched),
        "max_drawdown_amount": _max_drawdown(enriched),
        "api_statuses": sorted({row["api_status"] for row in enriched}),
        "odds_regime": by_regime,
        "favorite_rank_buckets": dict(sorted(favorite_rank_counter.items())),
        "candidates": [
            {
                "race_id": row["race_id"],
                "selection": row["selection"],
                "odds": row["odds"],
                "odds_regime": row["odds_regime"],
                "favorite_rank": row["favorite_rank"],
                "stake": row["stake"],
                "profit": row["profit"],
                "hit": row["hit"],
                "api_status": row["api_status"],
            }
            for row in enriched
        ],
        "interpretation": (
            "Sandbox-only evaluation. Use this to detect plumbing and candidate-selection issues before paid data; "
            "do not use it for Stage 4 evidence or profitability claims."
        ),
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(_markdown(summary), encoding="utf-8")
    return summary


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Pre-Contract Sandbox Evaluation",
        "",
        "Status: sandbox-only, not Stage 4 evidence.",
        "",
        "## Summary",
        "",
        f"- Races: {summary['race_count']}",
        f"- Candidates: {summary['candidate_count']}",
        f"- Stake sum: {summary['stake_sum']:.0f}",
        f"- Profit sum: {summary['profit_sum']:.0f}",
        f"- ROI: {_fmt_pct(summary['roi'])}",
        f"- Hits: {summary['hit_sum']}",
        f"- Hit rate: {_fmt_pct(summary['hit_rate'])}",
        f"- Max consecutive losses: {summary['max_consecutive_losses']}",
        f"- Max drawdown amount: {summary['max_drawdown_amount']:.0f}",
        f"- API statuses: {', '.join(summary['api_statuses']) if summary['api_statuses'] else 'n/a'}",
        "",
        "## Odds Regime",
        "",
        "| Regime | Bets | Stake | Profit | ROI | Hits |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for regime, row in summary["odds_regime"].items():
        lines.append(
            f"| {regime} | {row['bets']} | {row['stake_sum']:.0f} | {row['profit_sum']:.0f} | {_fmt_pct(row['roi'])} | {row['hit_sum']} |"
        )
    lines.extend(
        [
            "",
            "## Favorite Rank Buckets",
            "",
            "| Bucket | Count |",
            "|---|---:|",
        ]
    )
    for bucket, count in summary["favorite_rank_buckets"].items():
        lines.append(f"| {bucket} | {count} |")
    lines.extend(
        [
            "",
            "## Candidates",
            "",
            "| Race | Selection | Odds | Regime | Favorite Rank | Stake | Profit | Hit |",
            "|---|---:|---:|---|---:|---:|---:|---:|",
        ]
    )
    for row in summary["candidates"]:
        lines.append(
            f"| {row['race_id']} | {row['selection']} | {row['odds']:.1f} | {row['odds_regime']} | "
            f"{row['favorite_rank']} | {row['stake']:.0f} | {row['profit']:.0f} | {row['hit']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            str(summary["interpretation"]),
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate pre-contract sandbox shadow results")
    parser.add_argument("--bets-csv", default="reports/data_collection/pre_contract_sandbox/bets.csv")
    parser.add_argument("--shadow-input-csv", default="reports/data_collection/pre_contract_sandbox/shadow_input.csv")
    parser.add_argument("--output-json", default="reports/data_collection/pre_contract_sandbox_eval_status.json")
    parser.add_argument("--output-md", default="reports/data_collection/pre_contract_sandbox_eval.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = evaluate_pre_contract_sandbox(
        bets_csv=Path(args.bets_csv),
        shadow_input_csv=Path(args.shadow_input_csv),
        output_json=Path(args.output_json),
        output_md=Path(args.output_md),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
