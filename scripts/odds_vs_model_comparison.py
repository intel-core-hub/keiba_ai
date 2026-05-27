from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.market_attribution_utils import load_dataset, market_copy_score, summarize_variants
from scripts.odds_ablation import evaluate_variant


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Odds vs model comparison")
    parser.add_argument("--input", default="data/processed/historical_dataset.csv", help="入力CSV")
    parser.add_argument("--outdir", default="results/odds_vs_model", help="出力先ディレクトリ")
    parser.add_argument("--model-kind", choices=("boosted", "logistic"), default="boosted")
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--folds", type=int, default=3)
    return parser.parse_args()


def create_delta_table(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty or "variant" not in summary.columns:
        return pd.DataFrame()

    full = summary.loc[summary["variant"] == "full"].iloc[0].to_dict() if (summary["variant"] == "full").any() else {}
    rows = []
    for _, row in summary.iterrows():
        record = row.to_dict()
        record["delta_brier_vs_full"] = round(float(record.get("brier", float("nan")) - full.get("brier", float("nan"))), 6) if full else float("nan")
        record["delta_roi_vs_full"] = round(float(record.get("roi_top1", float("nan")) - full.get("roi_top1", float("nan"))), 6) if full else float("nan")
        record["delta_uncertainty_vs_full"] = round(float(record.get("uncertainty_mean", float("nan")) - full.get("uncertainty_mean", float("nan"))), 6) if full else float("nan")
        record["delta_edge_mae_vs_full"] = round(float(record.get("edge_mae", float("nan")) - full.get("edge_mae", float("nan"))), 6) if full else float("nan")
        rows.append(record)
    return pd.DataFrame(rows)


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


def plot_deltas(frame: pd.DataFrame, outdir: Path) -> None:
    if frame.empty:
        return

    metrics = [
        ("delta_brier_vs_full", "Brier delta"),
        ("delta_roi_vs_full", "ROI delta"),
        ("delta_uncertainty_vs_full", "Uncertainty delta"),
    ]
    fig, axes = plt.subplots(len(metrics), 1, figsize=(10, 12), sharex=True)
    if len(metrics) == 1:
        axes = [axes]

    for ax, (column, title) in zip(axes, metrics):
        if column in frame.columns:
            ax.bar(frame["variant"].astype(str), frame[column].fillna(0.0))
            ax.axhline(0.0, color="black", linewidth=0.8)
            ax.set_title(title)
            ax.tick_params(axis="x", rotation=20)

    fig.tight_layout()
    fig.savefig(outdir / "odds_model_deltas.png", dpi=160)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_dataset(args.input)
    variants = ["full", "no_odds", "market_only", "early_odds_only", "closing_odds"]
    evaluations = [evaluate_variant(df, variant, args.model_kind, args.train_ratio, args.folds) for variant in variants]
    summary = summarize_variants(evaluations)
    delta = create_delta_table(summary)

    full = next((item for item in evaluations if item.name == "full"), None)
    no_odds = next((item for item in evaluations if item.name == "no_odds"), None)
    market_only = next((item for item in evaluations if item.name == "market_only"), None)
    if not summary.empty:
        score = market_copy_score(full.metrics if full else {}, no_odds.metrics if no_odds else {}, market_only.metrics if market_only else {})
        for key, value in score.items():
            summary.loc[summary["variant"] == "full", key] = value
            delta.loc[delta["variant"] == "full", key] = value

    summary.to_csv(outdir / "comparison_summary.csv", index=False, encoding="utf-8-sig")
    delta.to_csv(outdir / "comparison_delta.csv", index=False, encoding="utf-8-sig")
    plot_deltas(delta, outdir)

    md_lines = ["# Odds vs Model Comparison", "", dataframe_to_markdown(delta)]
    (outdir / "comparison_report.md").write_text("\n".join(md_lines), encoding="utf-8")

    cols = [c for c in ["variant", "brier", "roi_top1", "calibration_gap", "uncertainty_mean", "market_corr", "market_copy_score"] if c in delta.columns]
    if cols:
        print()
        print(delta[cols].to_string(index=False))
    logger.info("saved: %s", outdir)


if __name__ == "__main__":
    main()