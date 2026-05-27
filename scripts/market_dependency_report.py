from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.market_attribution_utils import add_regime_labels, market_copy_score, select_top1_bets, summarize_variants
from scripts.odds_ablation import evaluate_variant
from scripts.market_attribution_utils import load_dataset


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Market dependency report")
    parser.add_argument("--input", default="data/processed/historical_dataset.csv", help="入力CSV")
    parser.add_argument("--outdir", default="results/market_dependency", help="出力先ディレクトリ")
    parser.add_argument("--model-kind", choices=("boosted", "logistic"), default="boosted")
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--folds", type=int, default=3)
    return parser.parse_args()


def regime_summary(selected: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if selected.empty or group_col not in selected.columns:
        return pd.DataFrame()

    rows = []
    for group_name, group in selected.groupby(group_col, dropna=False):
        rows.append({
            group_col: group_name,
            "bets": int(len(group)),
            "hit_rate_pct": round(float(group["hit"].mean() * 100.0), 2),
            "roi_pct": round(float((group["realized_profit"].sum() / len(group) + 1.0) * 100.0), 2),
            "avg_pred_prob": round(float(group["pred_prob"].mean()), 6),
            "avg_market_prob": round(float(group["market_probability"].mean()), 6) if "market_probability" in group.columns else None,
            "calibration_gap": round(float(group["calibration_gap"].mean()), 6) if "calibration_gap" in group.columns else None,
            "edge_mae": round(float((group["expected_profit"] - group["realized_profit"]).abs().mean()), 6) if "expected_profit" in group.columns else None,
        })

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    order = ["FAVORITE_HEAVY", "FAVORITE_TO_BALANCED", "BALANCED", "LONGSHOT", "DEEP_LONGSHOT", "UNKNOWN", "OTHER"]
    if group_col == "odds_regime":
        frame[group_col] = pd.Categorical(frame[group_col], categories=order, ordered=True)
        frame = frame.sort_values(group_col)
    else:
        frame = frame.sort_values(group_col)
    return frame.reset_index(drop=True)


def dataframe_to_markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No data"
    rows = frame.copy().astype(object).where(pd.notna(frame), "").astype(str)
    headers = list(rows.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in rows.iterrows():
        lines.append("| " + " | ".join(row[column] for column in headers) + " |")
    return "\n".join(lines)


def write_markdown(path: Path, title: str, summary: pd.DataFrame, odds_table: pd.DataFrame, class_table: pd.DataFrame, notes: list[str]) -> None:
    lines = [f"# {title}", ""]
    lines.append("## Variant Summary")
    lines.append(dataframe_to_markdown(summary))
    lines.append("")
    lines.append("## Odds Regime Dependence")
    lines.append(dataframe_to_markdown(odds_table))
    lines.append("")
    lines.append("## Race Class Dependence")
    lines.append(dataframe_to_markdown(class_table))
    lines.append("")
    lines.append("## Notes")
    for note in notes:
        lines.append(f"- {note}")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = add_regime_labels(load_dataset(args.input))
    variants = ["full", "no_odds", "market_only", "early_odds_only", "closing_odds"]
    evaluations = [evaluate_variant(df, variant, args.model_kind, args.train_ratio, args.folds) for variant in variants]
    summary = summarize_variants(evaluations)

    full = next((item for item in evaluations if item.name == "full"), None)
    no_odds = next((item for item in evaluations if item.name == "no_odds"), None)
    market_only = next((item for item in evaluations if item.name == "market_only"), None)
    market_score = market_copy_score(full.metrics if full else {}, no_odds.metrics if no_odds else {}, market_only.metrics if market_only else {})
    if not summary.empty:
        for key, value in market_score.items():
            summary.loc[summary["variant"] == "full", key] = value

    selected_frames = {
        item.name: select_top1_bets(item.predictions) if item.predictions is not None else pd.DataFrame()
        for item in evaluations
    }

    odds_rows = []
    class_rows = []
    for variant_name, selected in selected_frames.items():
        if selected.empty:
            continue
        odds_part = regime_summary(selected, "odds_regime")
        if not odds_part.empty:
            odds_part.insert(0, "variant", variant_name)
            odds_rows.append(odds_part)
        class_part = regime_summary(selected, "race_class")
        if not class_part.empty:
            class_part.insert(0, "variant", variant_name)
            class_rows.append(class_part)

    odds_table = pd.concat(odds_rows, ignore_index=True) if odds_rows else pd.DataFrame()
    class_table = pd.concat(class_rows, ignore_index=True) if class_rows else pd.DataFrame()

    summary.to_csv(outdir / "variant_summary.csv", index=False, encoding="utf-8-sig")
    odds_table.to_csv(outdir / "odds_regime_summary.csv", index=False, encoding="utf-8-sig")
    class_table.to_csv(outdir / "race_class_summary.csv", index=False, encoding="utf-8-sig")

    notes = [
        f"market_copy_score={market_score['market_copy_score']}",
        "higher market_copy_score means stronger dependence on odds and market-aligned signals",
        "early/closing odds variants are marked unavailable when matching columns do not exist in the input data",
    ]
    write_markdown(outdir / "market_dependency_report.md", "Market Dependency Report", summary, odds_table, class_table, notes)

    print()
    print(summary[[c for c in ["variant", "brier", "roi_top1", "uncertainty_mean", "market_corr", "market_copy_score"] if c in summary.columns]].to_string(index=False))
    logger.info("saved: %s", outdir)


if __name__ == "__main__":
    main()