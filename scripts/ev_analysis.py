# scripts/ev_analysis.py
#
# 競馬AIのEV検証を行う。
# 目的:
# - prediction accuracy と betting profitability を分離する
# - odds / confidence / race class / market regime 別 ROI を測る
# - expected return と realized return のズレを可視化する
#
# 使い方:
#   python scripts/ev_analysis.py
#   python scripts/ev_analysis.py --input results/backtest_full.csv
#   python scripts/ev_analysis.py --input results/backtest_full.csv --outdir results/ev_analysis

import argparse
import logging
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

EPS = 1e-6
ODDS_BINS = [0, 1.5, 2.5, 4, 6, 10, 20, 50, math.inf]
CONFIDENCE_BINS = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
EDGE_BINS = [-math.inf, -0.5, -0.2, 0.0, 0.2, 0.5, 1.0, math.inf]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EV analysis for horse racing bets")
    parser.add_argument(
        "--input",
        default="results/backtest_full.csv",
        help="ベット結果CSVの入力パス",
    )
    parser.add_argument(
        "--outdir",
        default="results/ev_analysis",
        help="出力先ディレクトリ",
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
        hit = pd.to_numeric(df["hit"], errors="coerce")
    elif "target_win" in df.columns:
        hit = pd.to_numeric(df["target_win"], errors="coerce")
    elif "actual_pos" in df.columns:
        hit = (pd.to_numeric(df["actual_pos"], errors="coerce") == 1).astype(int)
    else:
        raise ValueError("target column not found")

    df = df.copy()
    df["pred_prob"] = pd.to_numeric(df[prob_col], errors="coerce")
    df["hit"] = hit
    df["odds"] = pd.to_numeric(df.get("odds"), errors="coerce")
    df["pnl"] = pd.to_numeric(df.get("pnl"), errors="coerce")

    if "expected_value" in df.columns:
        df["expected_value"] = pd.to_numeric(df["expected_value"], errors="coerce")
    else:
        df["expected_value"] = df["pred_prob"] * df["odds"]

    df = df.dropna(subset=["pred_prob", "hit", "odds", "pnl"]).reset_index(drop=True)
    df["hit"] = df["hit"].astype(int)
    df["expected_profit"] = df["expected_value"] - 1.0
    df["realized_profit"] = df["pnl"].astype(float)
    df["realized_roi_pct"] = (df["realized_profit"] + 1.0) * 100.0
    df["expected_roi_pct"] = df["expected_value"] * 100.0
    df["calibration_gap"] = (df["pred_prob"] - df["hit"]).abs()
    df["edge_error"] = df["expected_profit"] - df["realized_profit"]

    if "race_title" in df.columns:
        df["race_class"] = df["race_title"].astype(str).apply(infer_race_class)
    else:
        df["race_class"] = "UNKNOWN"

    df["market_regime"] = df.apply(infer_market_regime, axis=1)

    if "race_id" in df.columns:
        df = df.sort_values(["race_id"]).reset_index(drop=True)

    logger.info("input rows: %d", len(df))
    logger.info("bets: %d, races: %d", len(df), df["race_id"].nunique() if "race_id" in df.columns else 0)
    return df


def infer_race_class(title: str) -> str:
    text = str(title)

    rules = [
        ("障害", "JUMP"),
        ("G1", "GRADE_1"),
        ("Ｇ１", "GRADE_1"),
        ("G2", "GRADE_2"),
        ("Ｇ２", "GRADE_2"),
        ("G3", "GRADE_3"),
        ("Ｇ３", "GRADE_3"),
        ("オープン", "OPEN"),
        ("OP", "OPEN"),
        ("3勝クラス", "CLASS_3W"),
        ("2勝クラス", "CLASS_2W"),
        ("1勝クラス", "CLASS_1W"),
        ("新馬", "DEBUT"),
        ("未勝利", "MAIDEN"),
        ("特別", "SPECIAL"),
        ("ステークス", "OPEN"),
        ("記念", "OPEN"),
        ("杯", "OPEN"),
        ("賞", "SPECIAL"),
        ("重賞", "STAKES"),
    ]

    for keyword, label in rules:
        if keyword in text:
            return label

    if any(token in text for token in ["3歳", "4歳", "5歳", "6歳"]):
        return "OPEN_AGE"

    return "OTHER"


def infer_market_regime(row: pd.Series) -> str:
    odds = row.get("odds", np.nan)
    ev = row.get("expected_value", np.nan)

    if pd.isna(odds):
        return "UNKNOWN"

    if odds <= 2.0:
        return "FAVORITE_HEAVY"
    if odds <= 4.0:
        return "FAVORITE_TO_BALANCED"
    if odds <= 8.0:
        return "BALANCED"
    if odds <= 20.0:
        return "LONGSHOT"
    if odds > 20.0:
        return "DEEP_LONGSHOT"

    return "UNKNOWN"


def bin_frame(df: pd.DataFrame, column: str, bins, labels=None, right=True) -> pd.DataFrame:
    out = df.copy()
    out["bin"] = pd.cut(out[column], bins=bins, labels=labels, include_lowest=True, right=right)
    return out


def summarize_group(group: pd.DataFrame) -> dict:
    count = len(group)
    if count == 0:
        return {}

    total_profit = float(group["realized_profit"].sum())
    realized_roi = (total_profit / count + 1.0) * 100.0
    expected_roi = float(group["expected_roi_pct"].mean())
    avg_pred = float(group["pred_prob"].mean())
    hit_rate = float(group["hit"].mean())
    avg_odds = float(group["odds"].mean())
    avg_ev = float(group["expected_value"].mean())
    avg_expected_profit = float(group["expected_profit"].mean())
    avg_realized_profit = float(group["realized_profit"].mean())
    avg_cal_gap = float(group["calibration_gap"].mean())
    avg_edge_error = float(group["edge_error"].mean())

    return {
        "count": count,
        "hit_rate": round(hit_rate * 100.0, 2),
        "avg_pred_prob": round(avg_pred, 4),
        "avg_odds": round(avg_odds, 2),
        "avg_expected_value": round(avg_ev, 4),
        "expected_roi_pct": round(expected_roi, 2),
        "realized_roi_pct": round(realized_roi, 2),
        "avg_expected_profit": round(avg_expected_profit, 4),
        "avg_realized_profit": round(avg_realized_profit, 4),
        "calibration_gap": round(avg_cal_gap, 4),
        "avg_edge_error": round(avg_edge_error, 4),
        "total_profit": round(total_profit, 4),
    }


def group_analysis(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for key, group in df.groupby(group_col, dropna=False):
        summary = summarize_group(group)
        if not summary:
            continue
        summary[group_col] = key
        rows.append(summary)

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    cols = [group_col, "count", "hit_rate", "avg_pred_prob", "avg_odds", "avg_expected_value", "expected_roi_pct", "realized_roi_pct", "avg_expected_profit", "avg_realized_profit", "calibration_gap", "avg_edge_error", "total_profit"]
    return out[cols].sort_values("realized_roi_pct", ascending=False).reset_index(drop=True)


def bin_analysis(df: pd.DataFrame, column: str, bins, labels=None, name: str = "bin") -> pd.DataFrame:
    framed = bin_frame(df, column, bins=bins, labels=labels)
    rows = []
    for key, group in framed.groupby("bin", dropna=False):
        summary = summarize_group(group)
        if not summary:
            continue
        summary[name] = str(key)
        rows.append(summary)

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    cols = [name, "count", "hit_rate", "avg_pred_prob", "avg_odds", "avg_expected_value", "expected_roi_pct", "realized_roi_pct", "avg_expected_profit", "avg_realized_profit", "calibration_gap", "avg_edge_error", "total_profit"]
    return out[cols].sort_values(name).reset_index(drop=True)


def edge_quality_analysis(df: pd.DataFrame) -> pd.DataFrame:
    edge_bins = bin_frame(df, "expected_profit", bins=EDGE_BINS)
    rows = []
    for key, group in edge_bins.groupby("bin", dropna=False):
        summary = summarize_group(group)
        if not summary:
            continue
        summary["edge_bin"] = str(key)
        summary["edge_precision"] = round(float((group["realized_profit"] > 0).mean() * 100.0), 2)
        summary["positive_edge_rate"] = round(float((group["expected_profit"] > 0).mean() * 100.0), 2)
        summary["edge_mae"] = round(float(np.mean(np.abs(group["expected_profit"] - group["realized_profit"]))), 4)
        rows.append(summary)

    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out

    cols = ["edge_bin", "count", "positive_edge_rate", "edge_precision", "avg_expected_profit", "avg_realized_profit", "edge_mae", "expected_roi_pct", "realized_roi_pct", "calibration_gap", "avg_edge_error", "total_profit"]
    return out[cols].sort_values("edge_bin").reset_index(drop=True)


def roi_curve(df: pd.DataFrame) -> pd.DataFrame:
    ordered = df.sort_values(["expected_value", "odds"], ascending=[False, True]).reset_index(drop=True)
    if len(ordered) == 0:
        return pd.DataFrame()

    rows = []
    for fraction in np.linspace(0.05, 1.0, 20):
        n = max(1, int(len(ordered) * fraction))
        subset = ordered.iloc[:n]
        total_profit = float(subset["realized_profit"].sum())
        realized_roi = (total_profit / n + 1.0) * 100.0
        expected_roi = float(subset["expected_roi_pct"].mean())
        rows.append({
            "top_fraction": round(float(fraction), 2),
            "bets": n,
            "realized_roi_pct": round(realized_roi, 2),
            "expected_roi_pct": round(expected_roi, 2),
            "total_profit": round(total_profit, 4),
            "avg_expected_value": round(float(subset["expected_value"].mean()), 4),
            "avg_expected_profit": round(float(subset["expected_profit"].mean()), 4),
            "avg_realized_profit": round(float(subset["realized_profit"].mean()), 4),
        })

    return pd.DataFrame(rows)


def confidence_roi_curve(df: pd.DataFrame) -> pd.DataFrame:
    framed = bin_frame(df, "pred_prob", bins=CONFIDENCE_BINS)
    rows = []
    for key, group in framed.groupby("bin", dropna=False):
        if len(group) == 0:
            continue
        summary = summarize_group(group)
        if not summary:
            continue
        summary["confidence_bin"] = str(key)
        summary["avg_calibration_gap"] = round(float(group["calibration_gap"].mean()), 4)
        rows.append(summary)

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    cols = ["confidence_bin", "count", "avg_pred_prob", "hit_rate", "avg_odds", "avg_expected_value", "expected_roi_pct", "realized_roi_pct", "calibration_gap", "avg_edge_error", "total_profit", "avg_calibration_gap"]
    return out[cols].sort_values("confidence_bin").reset_index(drop=True)


def odds_bin_analysis(df: pd.DataFrame) -> pd.DataFrame:
    labels = ["0-1.5", "1.5-2.5", "2.5-4", "4-6", "6-10", "10-20", "20-50", "50+"]
    framed = bin_frame(df, "odds", bins=ODDS_BINS, labels=labels)
    rows = []
    for key, group in framed.groupby("bin", dropna=False):
        summary = summarize_group(group)
        if not summary:
            continue
        summary["odds_bin"] = str(key)
        summary["avg_implied_prob"] = round(float(np.mean(1.0 / group["odds"])) , 4)
        summary["market_efficiency_gap"] = round(abs(summary["avg_pred_prob"] - summary["avg_implied_prob"]), 4)
        rows.append(summary)

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    cols = ["odds_bin", "count", "hit_rate", "avg_pred_prob", "avg_implied_prob", "avg_odds", "avg_expected_value", "expected_roi_pct", "realized_roi_pct", "calibration_gap", "avg_edge_error", "market_efficiency_gap", "total_profit"]
    return out[cols].sort_values("odds_bin").reset_index(drop=True)


def confidence_vs_roi_relation(conf_df: pd.DataFrame, roi_curve_df: pd.DataFrame) -> dict:
    if len(conf_df) == 0:
        return {}

    relation = {
        "confidence_roi_corr": None,
        "confidence_gap_roi_corr": None,
        "confidence_hit_roi_corr": None,
    }

    if len(conf_df) >= 2:
        relation["confidence_roi_corr"] = round(float(conf_df["avg_pred_prob"].corr(conf_df["realized_roi_pct"])), 4)
        relation["confidence_gap_roi_corr"] = round(float(conf_df["calibration_gap"].corr(conf_df["realized_roi_pct"])), 4)
        relation["confidence_hit_roi_corr"] = round(float(conf_df["hit_rate"].corr(conf_df["realized_roi_pct"])), 4)

    if len(roi_curve_df) >= 2:
        relation["roi_curve_slope"] = round(float(np.polyfit(roi_curve_df["top_fraction"], roi_curve_df["realized_roi_pct"], 1)[0]), 4)
    else:
        relation["roi_curve_slope"] = None

    return relation


def plot_roi_curve(curve_df: pd.DataFrame, outpath: Path) -> None:
    if len(curve_df) == 0:
        return

    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(curve_df["top_fraction"], curve_df["realized_roi_pct"], marker="o", linewidth=2, label="Realized ROI")
    ax.plot(curve_df["top_fraction"], curve_df["expected_roi_pct"], marker="s", linewidth=2, label="Expected ROI")
    ax.axhline(100.0, linestyle="--", color="gray", linewidth=1, label="Break-even 100%")
    ax.set_title("ROI Curve by Expected Value Rank")
    ax.set_xlabel("Top fraction of bets selected by expected value")
    ax.set_ylabel("ROI (%)")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(outpath, dpi=160)
    plt.close(fig)


def plot_expected_vs_realized(edge_df: pd.DataFrame, outpath: Path) -> None:
    if len(edge_df) == 0:
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(edge_df["edge_bin"], edge_df["avg_expected_profit"], marker="o", linewidth=2, label="Expected profit")
    ax.plot(edge_df["edge_bin"], edge_df["avg_realized_profit"], marker="s", linewidth=2, label="Realized profit")
    ax.axhline(0.0, linestyle="--", color="gray", linewidth=1)
    ax.set_title("Expected vs Realized Return by Edge Bin")
    ax.set_xlabel("Edge bin (expected profit = EV - 1)")
    ax.set_ylabel("Profit per bet")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(outpath, dpi=160)
    plt.close(fig)


def print_summary(df: pd.DataFrame, odds_df: pd.DataFrame, conf_df: pd.DataFrame, class_df: pd.DataFrame, regime_df: pd.DataFrame, edge_df: pd.DataFrame, relation: dict, outdir: Path) -> None:
    total_bets = len(df)
    total_profit = float(df["realized_profit"].sum())
    realized_roi = (total_profit / total_bets + 1.0) * 100.0 if total_bets else 0.0
    expected_roi = float(df["expected_roi_pct"].mean()) if total_bets else 0.0
    hit_rate = float(df["hit"].mean() * 100.0) if total_bets else 0.0
    avg_pred = float(df["pred_prob"].mean()) if total_bets else 0.0
    actual_rate = float(df["hit"].mean()) if total_bets else 0.0
    ece = float((df["pred_prob"] - df["hit"]).abs().mean()) if total_bets else 0.0

    print()
    print("=" * 78)
    print("  EV Validation Report")
    print("=" * 78)
    print(f"  bets: {total_bets:,}")
    print(f"  total profit: {total_profit:+.4f}")
    print(f"  realized ROI: {realized_roi:.2f}%")
    print(f"  expected ROI: {expected_roi:.2f}%")
    print(f"  hit rate: {hit_rate:.2f}%")
    print(f"  avg predicted probability: {avg_pred:.4f}")
    print(f"  actual hit rate: {actual_rate:.4f}")
    print(f"  calibration gap (mean |p-y|): {ece:.4f}")
    print()
    print("  [Calibration vs ROI]")
    if relation:
        for key, value in relation.items():
            print(f"    {key}: {value}")
    print()
    print("  [Odds ROI]")
    print(odds_df.to_string(index=False) if len(odds_df) else "    no data")
    print()
    print("  [Confidence ROI]")
    print(conf_df.to_string(index=False) if len(conf_df) else "    no data")
    print()
    print("  [Race Class ROI]")
    print(class_df.to_string(index=False) if len(class_df) else "    no data")
    print()
    print("  [Market Regime ROI]")
    print(regime_df.to_string(index=False) if len(regime_df) else "    no data")
    print()
    print("  [Edge Quality]")
    print(edge_df.to_string(index=False) if len(edge_df) else "    no data")
    print()
    print(f"  outputs saved to: {outdir}")
    print("=" * 78)


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_data(args.input)

    odds_df = odds_bin_analysis(df)
    conf_df = confidence_roi_curve(df)
    class_df = group_analysis(df, "race_class")
    regime_df = group_analysis(df, "market_regime")
    edge_df = edge_quality_analysis(df)
    roi_curve_df = roi_curve(df)
    relation = confidence_vs_roi_relation(conf_df, roi_curve_df)

    # Main outputs
    df.to_csv(outdir / "ev_enriched_bets.csv", index=False, encoding="utf-8-sig")
    odds_df.to_csv(outdir / "odds_roi.csv", index=False, encoding="utf-8-sig")
    conf_df.to_csv(outdir / "confidence_roi.csv", index=False, encoding="utf-8-sig")
    class_df.to_csv(outdir / "race_class_roi.csv", index=False, encoding="utf-8-sig")
    regime_df.to_csv(outdir / "market_regime_roi.csv", index=False, encoding="utf-8-sig")
    edge_df.to_csv(outdir / "edge_quality.csv", index=False, encoding="utf-8-sig")
    roi_curve_df.to_csv(outdir / "roi_curve.csv", index=False, encoding="utf-8-sig")

    plot_roi_curve(roi_curve_df, outdir / "roi_curve.png")
    plot_expected_vs_realized(edge_df, outdir / "expected_vs_realized.png")

    print_summary(df, odds_df, conf_df, class_df, regime_df, edge_df, relation, outdir)

    logger.info("saved: %s", outdir / "odds_roi.csv")
    logger.info("saved: %s", outdir / "confidence_roi.csv")
    logger.info("saved: %s", outdir / "race_class_roi.csv")
    logger.info("saved: %s", outdir / "market_regime_roi.csv")
    logger.info("saved: %s", outdir / "edge_quality.csv")
    logger.info("saved: %s", outdir / "roi_curve.csv")
    logger.info("saved: %s", outdir / "roi_curve.png")
    logger.info("saved: %s", outdir / "expected_vs_realized.png")


if __name__ == "__main__":
    main()
