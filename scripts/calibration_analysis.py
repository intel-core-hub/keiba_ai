# scripts/calibration_analysis.py
#
# 競馬AIの予測確率に対する calibration analysis を行う。
#
# 使い方:
#   python scripts/calibration_analysis.py
#   python scripts/calibration_analysis.py --input results/backtest_full.csv
#   python scripts/calibration_analysis.py --fit-ratio 0.7 --bins 10

import argparse
import logging
import math
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

EPS = 1e-6
DEFAULT_ODDS_BINS = [0, 1.5, 2.5, 4, 6, 10, 20, 50, math.inf]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prediction calibration analysis")
    parser.add_argument(
        "--input",
        default="results/backtest_full.csv",
        help="予測結果CSVの入力パス",
    )
    parser.add_argument(
        "--outdir",
        default="results/calibration_analysis",
        help="出力先ディレクトリ",
    )
    parser.add_argument(
        "--fit-ratio",
        type=float,
        default=0.7,
        help="校正器を学習する過去データ比率（時系列順）",
    )
    parser.add_argument(
        "--bins",
        type=int,
        default=10,
        help="confidence bins の数",
    )
    return parser.parse_args()


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)

    prob_col = None
    for candidate in ["pred_prob", "probability", "predicted_probability"]:
        if candidate in df.columns:
            prob_col = candidate
            break
    if prob_col is None:
        raise ValueError("prediction probability column not found")

    if "hit" in df.columns:
        y = pd.to_numeric(df["hit"], errors="coerce")
    elif "actual_pos" in df.columns:
        y = (pd.to_numeric(df["actual_pos"], errors="coerce") == 1).astype(int)
    elif "target_win" in df.columns:
        y = pd.to_numeric(df["target_win"], errors="coerce")
    else:
        raise ValueError("target column not found")

    df = df.copy()
    df["prob_raw"] = pd.to_numeric(df[prob_col], errors="coerce")
    df["y"] = y

    if "odds" in df.columns:
        df["odds"] = pd.to_numeric(df["odds"], errors="coerce")

    df = df.dropna(subset=["prob_raw", "y"]).reset_index(drop=True)
    df["y"] = df["y"].astype(int)

    if "race_id" in df.columns:
        df = df.sort_values(["race_id"]).reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    logger.info("input rows: %d", len(df))
    logger.info("probability column: %s", prob_col)
    return df


def temporal_split(df: pd.DataFrame, fit_ratio: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "race_id" in df.columns:
        race_order = df["race_id"].drop_duplicates().tolist()
        split_idx = max(1, int(len(race_order) * fit_ratio))
        split_idx = min(split_idx, len(race_order) - 1)
        fit_races = set(race_order[:split_idx])
        fit_df = df[df["race_id"].isin(fit_races)].copy()
        test_df = df[~df["race_id"].isin(fit_races)].copy()
    else:
        split_idx = max(1, int(len(df) * fit_ratio))
        split_idx = min(split_idx, len(df) - 1)
        fit_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()

    if len(fit_df) == 0 or len(test_df) == 0:
        raise ValueError("temporal split produced empty fit/test set")

    logger.info("fit rows: %d, test rows: %d", len(fit_df), len(test_df))
    return fit_df, test_df


def clip_probabilities(probabilities):
    return np.clip(np.asarray(probabilities, dtype=float), EPS, 1 - EPS)


def safe_logit(probabilities):
    probabilities = clip_probabilities(probabilities)
    return np.log(probabilities / (1.0 - probabilities))


def brier(y_true, y_prob):
    return round(float(brier_score_loss(y_true, clip_probabilities(y_prob))), 6)


def safe_log_loss(y_true, y_prob):
    return round(float(log_loss(y_true, clip_probabilities(y_prob), labels=[0, 1])), 6)


def ece_score(y_true, y_prob, bins=10):
    y_true = np.asarray(y_true, dtype=float)
    y_prob = clip_probabilities(y_prob)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(y_true)
    ece = 0.0

    for start, end in zip(edges[:-1], edges[1:]):
        if end == 1.0:
            mask = (y_prob >= start) & (y_prob <= end)
        else:
            mask = (y_prob >= start) & (y_prob < end)
        count = int(mask.sum())
        if count == 0:
            continue
        avg_prob = float(y_prob[mask].mean())
        avg_hit = float(y_true[mask].mean())
        ece += (count / total) * abs(avg_prob - avg_hit)

    return round(float(ece), 6)


def bin_table(y_true, y_prob, bins=10, bin_type="confidence", odds=None):
    y_true = np.asarray(y_true, dtype=float)
    y_prob = clip_probabilities(y_prob)

    if bin_type == "confidence":
        edges = np.linspace(0.0, 1.0, bins + 1)
        labels = []
        for start, end in zip(edges[:-1], edges[1:]):
            labels.append(f"{start:.1f}-{end:.1f}")
    elif bin_type == "odds":
        if odds is None:
            raise ValueError("odds is required for odds bins")
        odds = pd.to_numeric(pd.Series(odds), errors="coerce").to_numpy(dtype=float)
        edges = np.array(DEFAULT_ODDS_BINS, dtype=float)
        labels = []
        for start, end in zip(edges[:-1], edges[1:]):
            if math.isinf(end):
                labels.append(f"{start:g}+")
            else:
                labels.append(f"{start:g}-{end:g}")
    else:
        raise ValueError("invalid bin_type")

    records = []
    for idx, (start, end, label) in enumerate(zip(edges[:-1], edges[1:], labels)):
        if bin_type == "confidence":
            if end == 1.0:
                mask = (y_prob >= start) & (y_prob <= end)
            else:
                mask = (y_prob >= start) & (y_prob < end)
        else:
            if math.isinf(end):
                mask = (odds >= start)
            else:
                mask = (odds >= start) & (odds < end)

        count = int(mask.sum())
        if count == 0:
            continue

        avg_pred = float(y_prob[mask].mean())
        actual_rate = float(y_true[mask].mean())
        gap = avg_pred - actual_rate
        bias = "CALIBRATED"
        if gap > 0.03:
            bias = "OVERCONFIDENCE"
        elif gap < -0.03:
            bias = "UNDERCONFIDENCE"

        row = {
            "bin_type": bin_type,
            "bin_index": idx,
            "bin_label": label,
            "count": count,
            "avg_pred": round(avg_pred, 6),
            "actual_rate": round(actual_rate, 6),
            "gap": round(abs(gap), 6),
            "bias": bias,
            "model_minus_actual": round(gap, 6),
        }

        if bin_type == "odds":
            avg_odds = float(np.nanmean(odds[mask])) if np.any(mask) else np.nan
            implied = float(np.nanmean(1.0 / odds[mask])) if np.any(mask) else np.nan
            row.update({
                "avg_odds": round(avg_odds, 6) if not np.isnan(avg_odds) else None,
                "implied_prob": round(implied, 6) if not np.isnan(implied) else None,
                "model_minus_market": round(avg_pred - implied, 6) if not np.isnan(implied) else None,
            })

        records.append(row)

    return pd.DataFrame(records)


def fit_isotonic(fit_probs, fit_y):
    model = IsotonicRegression(out_of_bounds="clip")
    model.fit(clip_probabilities(fit_probs), np.asarray(fit_y, dtype=float))
    return model


def predict_isotonic(model, probs):
    return clip_probabilities(model.transform(clip_probabilities(probs)))


def fit_platt(fit_probs, fit_y):
    model = LogisticRegression(solver="lbfgs", max_iter=1000)
    model.fit(safe_logit(fit_probs).reshape(-1, 1), np.asarray(fit_y, dtype=int))
    return model


def predict_platt(model, probs):
    return model.predict_proba(safe_logit(probs).reshape(-1, 1))[:, 1]


def evaluate_variants(fit_df: pd.DataFrame, test_df: pd.DataFrame, bins: int):
    fit_y = fit_df["y"].to_numpy(dtype=int)
    test_y = test_df["y"].to_numpy(dtype=int)
    fit_probs = fit_df["prob_raw"].to_numpy(dtype=float)
    test_probs = test_df["prob_raw"].to_numpy(dtype=float)

    raw = test_probs

    variants = {
        "raw": raw,
    }

    if len(np.unique(fit_y)) >= 2 and len(np.unique(fit_probs)) >= 2:
        try:
            iso_model = fit_isotonic(fit_probs, fit_y)
            variants["isotonic"] = predict_isotonic(iso_model, test_probs)
        except Exception as exc:
            logger.warning("isotonic calibration failed: %s", exc)
            variants["isotonic"] = raw

        try:
            platt_model = fit_platt(fit_probs, fit_y)
            variants["platt"] = predict_platt(platt_model, test_probs)
        except Exception as exc:
            logger.warning("platt scaling failed: %s", exc)
            variants["platt"] = raw
    else:
        logger.warning("fit segment has insufficient class diversity; using raw probabilities")
        variants["isotonic"] = raw
        variants["platt"] = raw

    rows = []
    bin_rows = []
    for name, probs in variants.items():
        probs = clip_probabilities(probs)
        rows.append({
            "variant": name,
            "rows": len(test_y),
            "brier": brier(test_y, probs),
            "log_loss": safe_log_loss(test_y, probs),
            "ece": ece_score(test_y, probs, bins=bins),
            "avg_pred": round(float(np.mean(probs)), 6),
            "actual_rate": round(float(np.mean(test_y)), 6),
            "calibration_gap": round(float(abs(np.mean(probs) - np.mean(test_y))), 6),
        })

        conf_bins = bin_table(test_y, probs, bins=bins, bin_type="confidence")
        conf_bins.insert(0, "variant", name)
        bin_rows.append(conf_bins)

        if "odds" in test_df.columns:
            odds_bins = bin_table(test_y, probs, bins=bins, bin_type="odds", odds=test_df["odds"].to_numpy())
            odds_bins.insert(0, "variant", name)
            bin_rows.append(odds_bins)

    metrics_df = pd.DataFrame(rows)
    bins_df = pd.concat(bin_rows, ignore_index=True) if bin_rows else pd.DataFrame()
    return variants, metrics_df, bins_df


def summarize_biases(conf_bins: pd.DataFrame, odds_bins: pd.DataFrame) -> dict:
    summary = {}

    if len(conf_bins) > 0:
        summary["overconfident_bins"] = int((conf_bins["model_minus_actual"] > 0.03).sum())
        summary["underconfident_bins"] = int((conf_bins["model_minus_actual"] < -0.03).sum())
        summary["worst_confidence_bin"] = conf_bins.iloc[conf_bins["gap"].idxmax()]["bin_label"] if len(conf_bins) else None

    if len(odds_bins) > 0:
        longshot = odds_bins[odds_bins["bin_label"].str.contains("20\+|50\+|10-20|20-50", regex=True, na=False)]
        favorite = odds_bins[odds_bins["bin_label"].str.contains("0-1.5|1.5-2.5|2.5-4", regex=True, na=False)]
        summary["longshot_bias_mean"] = round(float(longshot["model_minus_actual"].mean()), 6) if len(longshot) else None
        summary["favorite_bias_mean"] = round(float(favorite["model_minus_actual"].mean()), 6) if len(favorite) else None
        summary["market_distortion_mean"] = round(float(odds_bins["model_minus_market"].abs().mean()), 6) if "model_minus_market" in odds_bins.columns else None

    return summary


def plot_reliability(variants: dict, test_y: np.ndarray, outpath: Path, bins: int):
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", linewidth=1.2, label="Perfect calibration")

    for name, probs in variants.items():
        table = bin_table(test_y, probs, bins=bins, bin_type="confidence")
        if len(table) == 0:
            continue
        ax.plot(
            table["avg_pred"],
            table["actual_rate"],
            marker="o",
            linewidth=2,
            label=name,
        )

    ax.set_title("Reliability Curve")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed win rate")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(outpath, dpi=160)
    plt.close(fig)


def plot_bin_calibration(conf_bins: pd.DataFrame, odds_bins: pd.DataFrame, outpath: Path):
    fig, axes = plt.subplots(2, 1, figsize=(12, 10))

    if len(conf_bins) > 0:
        axes[0].bar(conf_bins["bin_label"], conf_bins["actual_rate"], alpha=0.7, label="Observed win rate")
        axes[0].plot(conf_bins["bin_label"], conf_bins["avg_pred"], color="crimson", marker="o", linewidth=2, label="Mean predicted")
        axes[0].set_title("Confidence-bin calibration")
        axes[0].set_ylabel("Rate")
        axes[0].tick_params(axis="x", rotation=45)
        axes[0].grid(axis="y", alpha=0.25)
        axes[0].legend()
    else:
        axes[0].set_visible(False)

    if len(odds_bins) > 0:
        axes[1].bar(odds_bins["bin_label"], odds_bins["actual_rate"], alpha=0.7, label="Observed win rate")
        axes[1].plot(odds_bins["bin_label"], odds_bins["avg_pred"], color="darkgreen", marker="o", linewidth=2, label="Mean predicted")
        if "implied_prob" in odds_bins.columns:
            axes[1].plot(odds_bins["bin_label"], odds_bins["implied_prob"], color="slateblue", marker="s", linewidth=1.8, label="Market implied")
        axes[1].set_title("Odds-bin calibration")
        axes[1].set_ylabel("Rate")
        axes[1].tick_params(axis="x", rotation=45)
        axes[1].grid(axis="y", alpha=0.25)
        axes[1].legend()
    else:
        axes[1].set_visible(False)

    fig.tight_layout()
    fig.savefig(outpath, dpi=160)
    plt.close(fig)


def print_report(metrics_df: pd.DataFrame, bias_summary: dict, fit_df: pd.DataFrame, test_df: pd.DataFrame, outdir: Path):
    print()
    print("=" * 72)
    print("  Calibration Analysis Report")
    print("=" * 72)
    print(f"  fit rows: {len(fit_df):,}")
    print(f"  test rows: {len(test_df):,}")
    print(f"  output dir: {outdir}")
    print()
    print("  [Metrics]")
    print(metrics_df.to_string(index=False))
    print()
    print("  [Bias Summary]")
    for key, value in bias_summary.items():
        print(f"    {key}: {value}")
    print("=" * 72)


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_data(args.input)
    fit_df, test_df = temporal_split(df, args.fit_ratio)

    variants, metrics_df, bins_df = evaluate_variants(fit_df, test_df, args.bins)

    metrics_path = outdir / "calibration_metrics.csv"
    bins_path = outdir / "calibration_bins.csv"
    preds_path = outdir / "calibrated_predictions.csv"
    reliability_path = outdir / "reliability_curve.png"
    binplot_path = outdir / "bin_calibration.png"

    metrics_df.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    if len(bins_df) > 0:
        bins_df.to_csv(bins_path, index=False, encoding="utf-8-sig")

    test_y = test_df["y"].to_numpy(dtype=int)
    plot_reliability(variants, test_y, reliability_path, args.bins)

    if len(bins_df) > 0:
        raw_conf = bins_df[(bins_df["variant"] == "raw") & (bins_df["bin_type"] == "confidence")].copy()
        raw_odds = bins_df[(bins_df["variant"] == "raw") & (bins_df["bin_type"] == "odds")].copy()
        plot_bin_calibration(raw_conf, raw_odds, binplot_path)
        bias_summary = summarize_biases(raw_conf, raw_odds)
    else:
        bias_summary = {}

    raw_probs = clip_probabilities(test_df["prob_raw"].to_numpy(dtype=float))
    test_out = test_df.copy()
    test_out["prob_raw_clipped"] = raw_probs

    if "isotonic" in variants:
        test_out["prob_isotonic"] = variants["isotonic"]
    if "platt" in variants:
        test_out["prob_platt"] = variants["platt"]
    test_out.to_csv(preds_path, index=False, encoding="utf-8-sig")

    print_report(metrics_df, bias_summary, fit_df, test_df, outdir)
    logger.info("saved: %s", metrics_path)
    logger.info("saved: %s", bins_path)
    logger.info("saved: %s", preds_path)
    logger.info("saved: %s", reliability_path)
    logger.info("saved: %s", binplot_path)


if __name__ == "__main__":
    main()
