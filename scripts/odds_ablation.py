from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.market_attribution_utils import (
    VariantEvaluation,
    add_regime_labels,
    feature_columns_for_variant,
    fit_predict_variant,
    load_dataset,
    market_copy_score,
    summarize_variants,
    temporal_splits,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Odds ablation analysis")
    parser.add_argument("--input", default="data/processed/historical_dataset.csv", help="入力CSV")
    parser.add_argument("--outdir", default="results/odds_ablation", help="出力先ディレクトリ")
    parser.add_argument("--model-kind", choices=("boosted", "logistic"), default="boosted")
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--folds", type=int, default=3)
    return parser.parse_args()


def evaluate_variant(df: pd.DataFrame, variant: str, model_kind: str, train_ratio: float, folds: int) -> VariantEvaluation:
    feature_columns = feature_columns_for_variant(df, variant)
    if not feature_columns:
        return VariantEvaluation(
            name=variant,
            feature_columns=[],
            metrics={"available": 0.0},
            available=False,
            reason="no matching features",
        )

    fold_rows = []
    fold_metrics = []
    for train_df, test_df in temporal_splits(df, train_ratio=train_ratio, folds=folds):
        pred_df, metrics, used_features = fit_predict_variant(train_df, test_df, feature_columns, model_kind=model_kind)
        if pred_df is None:
            continue
        fold_rows.append(pred_df)
        fold_metrics.append(metrics)

    if not fold_metrics:
        return VariantEvaluation(
            name=variant,
            feature_columns=feature_columns,
            metrics={"available": 0.0},
            available=False,
            reason="insufficient data",
        )

    summary = {}
    numeric_keys = sorted({key for metrics in fold_metrics for key in metrics.keys()})
    for key in numeric_keys:
        values = [metrics.get(key) for metrics in fold_metrics if pd.notna(metrics.get(key))]
        if values:
            summary[key] = round(float(np.mean(values)), 6)

    combined = pd.concat(fold_rows, ignore_index=True) if fold_rows else None
    if combined is not None and "pred_prob" in combined.columns:
        summary["prediction_rows"] = float(len(combined))
        summary["distinct_races"] = float(combined["race_id"].nunique()) if "race_id" in combined.columns else float("nan")

    return VariantEvaluation(
        name=variant,
        feature_columns=feature_columns,
        metrics=summary,
        predictions=combined,
    )


def print_summary(frame: pd.DataFrame) -> None:
    if frame.empty:
        print("No results")
        return

    display_cols = [
        "variant",
        "available",
        "brier",
        "ece",
        "calibration_gap",
        "roi_top1",
        "top1_hit_rate",
        "uncertainty_mean",
        "uncertainty_high_rate",
        "market_corr",
        "market_mae",
        "edge_mae",
        "feature_count",
    ]
    cols = [column for column in display_cols if column in frame.columns]
    print()
    print(frame[cols].to_string(index=False))


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = add_regime_labels(load_dataset(args.input))
    variants = ["full", "no_odds", "market_only", "early_odds_only", "closing_odds"]

    evaluations = [evaluate_variant(df, variant, args.model_kind, args.train_ratio, args.folds) for variant in variants]
    summary = summarize_variants(evaluations)

    if not summary.empty:
        market_score = market_copy_score(
            summary.loc[summary["variant"] == "full"].iloc[0].to_dict() if (summary["variant"] == "full").any() else {},
            summary.loc[summary["variant"] == "no_odds"].iloc[0].to_dict() if (summary["variant"] == "no_odds").any() else {},
            summary.loc[summary["variant"] == "market_only"].iloc[0].to_dict() if (summary["variant"] == "market_only").any() else {},
        )
        for key, value in market_score.items():
            summary.loc[summary["variant"] == "full", key] = value

    summary_path = outdir / "odds_ablation_summary.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    report = {
        "input": args.input,
        "model_kind": args.model_kind,
        "train_ratio": args.train_ratio,
        "folds": args.folds,
        "variants": [
            {
                "name": item.name,
                "available": item.available,
                "reason": item.reason,
                "feature_columns": item.feature_columns,
                "metrics": item.metrics,
            }
            for item in evaluations
        ],
    }
    with open(outdir / "odds_ablation_summary.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, default=lambda obj: obj if isinstance(obj, (int, float, str, bool)) else None)

    print_summary(summary)
    logger.info("saved: %s", summary_path)


if __name__ == "__main__":
    main()