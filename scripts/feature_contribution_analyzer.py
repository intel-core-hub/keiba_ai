from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

warnings.filterwarnings("ignore", message="X does not have valid feature names*")
warnings.filterwarnings("ignore", category=FutureWarning)

from scripts.market_attribution_utils import (
    add_regime_labels,
    build_model,
    feature_columns_for_variant,
    load_dataset,
    numeric_feature_frame,
    select_top1_bets,
    target_series,
    temporal_splits,
    evaluate_predictions,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Feature contribution analyzer")
    parser.add_argument("--input", default="data/processed/historical_dataset.csv", help="入力CSV")
    parser.add_argument("--outdir", default="results/feature_contribution", help="出力先ディレクトリ")
    parser.add_argument("--variant", choices=("full", "no_odds", "market_only"), default="full")
    parser.add_argument("--model-kind", choices=("boosted", "logistic"), default="boosted")
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--local-samples", type=int, default=10)
    parser.add_argument("--random-state", type=int, default=42)
    return parser.parse_args()


def fit_variant(train_df: pd.DataFrame, test_df: pd.DataFrame, feature_cols: list[str], model_kind: str):
    x_train = numeric_feature_frame(train_df, feature_cols)
    x_test = numeric_feature_frame(test_df, feature_cols)
    y_train = target_series(train_df)

    class_counts = y_train.value_counts()
    min_class_count = int(class_counts.min()) if not class_counts.empty else 0
    calibrated = min_class_count >= 2 and len(x_train) >= 6
    cv_folds = max(2, min(3, min_class_count)) if calibrated else 2

    model = build_model(model_kind=model_kind, cv=cv_folds, calibrated=calibrated)
    model.fit(x_train, y_train)

    try:
        proba = model.predict_proba(x_test.values)[:, 1]
    except Exception:
        proba = np.full(len(x_test), float(y_train.mean() if len(y_train) else 0.5))

    pred_df = test_df.copy()
    pred_df["pred_prob"] = np.round(proba, 6)
    if "odds" in pred_df.columns:
        pred_df["expected_value"] = np.round(pred_df["pred_prob"] * pd.to_numeric(pred_df["odds"], errors="coerce"), 6)
        pred_df["market_probability"] = np.where(
            pd.to_numeric(pred_df["odds"], errors="coerce") > 0,
            1.0 / pd.to_numeric(pred_df["odds"], errors="coerce"),
            np.nan,
        )
    metrics = evaluate_predictions(pred_df)
    return model, pred_df, metrics, x_train.median(numeric_only=True)


def permutation_importance(model, test_df: pd.DataFrame, feature_cols: list[str], base_metrics: dict[str, float], random_state: int) -> pd.DataFrame:
    rng = np.random.default_rng(random_state)
    base_x = numeric_feature_frame(test_df, feature_cols)
    rows = []

    for feature in feature_cols:
        permuted = base_x.copy()
        permuted[feature] = rng.permutation(permuted[feature].to_numpy())
        pred_df = test_df.copy()
        pred_df["pred_prob"] = np.round(model.predict_proba(permuted.values)[:, 1], 6)
        if "odds" in pred_df.columns:
            pred_df["expected_value"] = np.round(pred_df["pred_prob"] * pd.to_numeric(pred_df["odds"], errors="coerce"), 6)
            pred_df["market_probability"] = np.where(
                pd.to_numeric(pred_df["odds"], errors="coerce") > 0,
                1.0 / pd.to_numeric(pred_df["odds"], errors="coerce"),
                np.nan,
            )
        metrics = evaluate_predictions(pred_df)
        rows.append({
            "feature": feature,
            "delta_brier": round(float(metrics["brier"] - base_metrics["brier"]), 6),
            "delta_ece": round(float(metrics["ece"] - base_metrics["ece"]), 6),
            "roi_drop": round(float(base_metrics.get("roi_top1", float("nan")) - metrics.get("roi_top1", float("nan"))), 6),
            "market_corr_drop": round(float(base_metrics.get("market_corr", float("nan")) - metrics.get("market_corr", float("nan"))), 6),
        })

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["abs_delta_brier"] = frame["delta_brier"].abs()
        frame = frame.sort_values(["delta_brier", "roi_drop"], ascending=False).reset_index(drop=True)
    return frame


def leave_one_out(train_df: pd.DataFrame, test_df: pd.DataFrame, feature_cols: list[str], base_metrics: dict[str, float], model_kind: str) -> pd.DataFrame:
    rows = []
    for feature in feature_cols:
        reduced = [column for column in feature_cols if column != feature]
        if not reduced:
            continue
        _, _, metrics, _ = fit_variant(train_df, test_df, reduced, model_kind)
        rows.append({
            "feature": feature,
            "delta_brier": round(float(metrics["brier"] - base_metrics["brier"]), 6),
            "delta_ece": round(float(metrics["ece"] - base_metrics["ece"]), 6),
            "roi_drop": round(float(base_metrics.get("roi_top1", float("nan")) - metrics.get("roi_top1", float("nan"))), 6),
            "uncertainty_delta": round(float(metrics.get("uncertainty_mean", float("nan")) - base_metrics.get("uncertainty_mean", float("nan"))), 6),
        })

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["importance_score"] = frame[["delta_brier", "roi_drop", "delta_ece"]].abs().sum(axis=1)
        frame = frame.sort_values("importance_score", ascending=False).reset_index(drop=True)
    return frame


def local_contributions(model, train_medians: pd.Series, test_df: pd.DataFrame, feature_cols: list[str], sample_count: int) -> pd.DataFrame:
    if len(test_df) == 0:
        return pd.DataFrame()

    base_row = train_medians.reindex(feature_cols).fillna(0.0).to_dict()
    baseline_frame = pd.DataFrame([base_row])
    baseline_prob = float(model.predict_proba(numeric_feature_frame(baseline_frame, feature_cols))[:, 1][0])

    top_rows = test_df.copy()
    if "pred_prob" in top_rows.columns:
        top_rows = top_rows.sort_values("pred_prob", ascending=False)
    top_rows = top_rows.head(sample_count)

    records = []
    for rank, (_, row) in enumerate(top_rows.iterrows(), start=1):
        actual_frame = pd.DataFrame([row.reindex(feature_cols).fillna(0.0).to_dict()])
        actual_prob = float(model.predict_proba(numeric_feature_frame(actual_frame, feature_cols))[:, 1][0])
        contributions = []
        for feature in feature_cols:
            perturbed = base_row.copy()
            perturbed[feature] = row.get(feature, base_row.get(feature, 0.0))
            perturbed_frame = pd.DataFrame([perturbed])
            perturbed_prob = float(model.predict_proba(numeric_feature_frame(perturbed_frame, feature_cols))[:, 1][0])
            contribution = perturbed_prob - baseline_prob
            contributions.append((feature, contribution))

        contribution_sum = sum(abs(value) for _, value in contributions) or 1.0
        market_abs = next((abs(value) for feature, value in contributions if feature == "odds"), 0.0)

        for feature, contribution in contributions:
            records.append({
                "rank": rank,
                "race_id": row.get("race_id", ""),
                "horse_name": row.get("horse_name", ""),
                "feature": feature,
                "contribution": round(float(contribution), 6),
                "abs_contribution": round(float(abs(contribution)), 6),
                "share_of_absolute": round(float(abs(contribution) / contribution_sum), 6),
                "market_share": round(float(market_abs / contribution_sum), 6),
                "baseline_prob": round(float(baseline_prob), 6),
                "actual_prob": round(float(actual_prob), 6),
                "prob_delta": round(float(actual_prob - baseline_prob), 6),
            })

    return pd.DataFrame(records)


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = add_regime_labels(load_dataset(args.input))
    feature_cols = feature_columns_for_variant(df, args.variant)
    if not feature_cols:
        raise SystemExit(f"No usable features for variant={args.variant}")

    splits = temporal_splits(df, train_ratio=args.train_ratio, folds=args.folds)
    train_df, test_df = splits[-1]

    model, pred_df, base_metrics, train_medians = fit_variant(train_df, test_df, feature_cols, args.model_kind)

    perm = permutation_importance(model, test_df, feature_cols, base_metrics, args.random_state)
    loo = leave_one_out(train_df, test_df, feature_cols, base_metrics, args.model_kind)
    local = local_contributions(model, train_medians, pred_df, feature_cols, args.local_samples)

    perm_path = outdir / "permutation_importance.csv"
    loo_path = outdir / "leave_one_out.csv"
    local_path = outdir / "local_contributions.csv"
    perm.to_csv(perm_path, index=False, encoding="utf-8-sig")
    loo.to_csv(loo_path, index=False, encoding="utf-8-sig")
    local.to_csv(local_path, index=False, encoding="utf-8-sig")

    odds_share = float(local.loc[local["feature"] == "odds", "share_of_absolute"].mean()) if not local.empty and (local["feature"] == "odds").any() else float("nan")
    summary = {
        "input": args.input,
        "variant": args.variant,
        "model_kind": args.model_kind,
        "base_metrics": base_metrics,
        "odds_local_share": odds_share,
        "top_permutation": perm.head(10).to_dict(orient="records"),
        "top_leave_one_out": loo.head(10).to_dict(orient="records"),
    }
    with open(outdir / "feature_contribution_summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print()
    print(pd.DataFrame([base_metrics]).to_string(index=False))
    if not perm.empty:
        print()
        print(perm.head(10).to_string(index=False))
    if not loo.empty:
        print()
        print(loo.head(10).to_string(index=False))
    logger.info("saved: %s", outdir)


if __name__ == "__main__":
    main()