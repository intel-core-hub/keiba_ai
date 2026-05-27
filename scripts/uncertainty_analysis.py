"""Uncertainty analysis

Simple, single-version script that:
- loads prediction CSV
- builds uncertainty profile on an initial temporal fit split
- scores the test portion with `estimate_uncertainty`
- writes `uncertainty_scored_test.csv`, `uncertainty_methods.csv`, simple plots

Designed to be robust to column name variations and large CSVs.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import warnings

import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from learning.uncertainty import build_uncertainty_profile, estimate_uncertainty


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Uncertainty analysis: score test set and summarize")
    p.add_argument("--input", "-i", required=True)
    p.add_argument("--outdir", "-o", default="results/uncertainty_analysis")
    p.add_argument("--fit-ratio", type=float, default=0.7)
    return p.parse_args()


def load_and_normalize(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, engine="python")
    # detect probability column
    prob_col = None
    for cand in ["pred_prob", "prob", "prediction", "probability"]:
        if cand in df.columns:
            prob_col = cand
            break
    if prob_col is None:
        raise RuntimeError("No probability column found (tried: pred_prob, prob, prediction, probability)")

    df = df.copy()
    df["pred_prob"] = pd.to_numeric(df[prob_col], errors="coerce")

    # derive hit if missing
    if "hit" not in df.columns:
        if "pnl" in df.columns:
            df["hit"] = (pd.to_numeric(df["pnl"], errors="coerce") > 0).astype(int)
        else:
            df["hit"] = 0

    # ensure numeric columns exist
    df["pnl"] = pd.to_numeric(df.get("pnl", 0), errors="coerce").fillna(0.0)
    df["odds"] = pd.to_numeric(df.get("odds", 0), errors="coerce").fillna(0.0)

    df = df.dropna(subset=["pred_prob"]).reset_index(drop=True)
    return df


def temporal_split(df: pd.DataFrame, fit_ratio: float):
    if "race_id" in df.columns:
        races = df["race_id"].drop_duplicates().tolist()
        split_idx = max(1, int(len(races) * fit_ratio))
        fit_races = set(races[:split_idx])
        fit_df = df[df["race_id"].isin(fit_races)].copy()
        test_df = df[~df["race_id"].isin(fit_races)].copy()
    else:
        split_idx = max(1, int(len(df) * fit_ratio))
        fit_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
    return fit_df, test_df


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_and_normalize(args.input)
    fit_df, test_df = temporal_split(df, args.fit_ratio)

    # build profile (keep bootstrap relatively small for speed)
    profile = build_uncertainty_profile(
        fit_df["pred_prob"].to_numpy(dtype=float),
        fit_df.get("hit", pd.Series([0] * len(fit_df))).to_numpy(dtype=int),
        bins=10,
        bootstrap_samples=200,
    )

    # score test set
    rows = [estimate_uncertainty(float(p), profile) for p in test_df["pred_prob"].to_numpy(dtype=float)]
    scored = pd.concat([test_df.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    scored.to_csv(outdir / "uncertainty_scored_test.csv", index=False, encoding="utf-8-sig")

    # produce simple methods table using quantiles from fit set
    methods = {"combined": "uncertainty_score", "entropy": "entropy", "bootstrap": "bootstrap_std", "conformal": "conformal_width"}
    records = []
    for name, col in methods.items():
        if col not in scored.columns:
            continue
        try:
            thresholds = [float(scored[col].quantile(q)) for q in [0.2, 0.4, 0.6, 0.8]]
        except Exception:
            thresholds = []
        for th in thresholds:
            sel = scored[scored[col] <= th]
            if sel.empty:
                continue
            total_pnl = float(sel["pnl"].sum()) if "pnl" in sel.columns else 0.0
            records.append({
                "method": name,
                "threshold": round(float(th), 6),
                "n_bets": len(sel),
                "coverage": round(len(sel) / len(scored), 4),
                "roi": round(total_pnl / max(1.0, len(sel)), 6),
                "hit_rate": round(float(sel["hit"].mean() if "hit" in sel.columns else 0.0), 4),
            })

    pd.DataFrame(records).to_csv(outdir / "uncertainty_methods.csv", index=False, encoding="utf-8-sig")

    # plots
    try:
        plt.figure(figsize=(8, 4))
        plt.hist(scored.get("uncertainty_score", np.zeros(len(scored))), bins=30)
        plt.title("Uncertainty distribution (test)")
        plt.tight_layout()
        plt.savefig(outdir / "uncertainty_hist.png")
        plt.close()
    except Exception:
        warnings.warn("failed to write uncertainty histogram")

    print("wrote outputs to", outdir)


if __name__ == "__main__":
    main()
