"""ROI decomposition and survival analysis for betting performance.

This report separates prediction quality, calibration quality, edge quality,
profitability, and variance luck using the available betting outputs.

Usage:
  python scripts/roi_analysis.py --input results/backtest_full.csv
  python scripts/roi_analysis.py --input results/backtest_full.csv --decision-log logs/decisions.jsonl --bets-log derived/bets.csv
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.roi_analyzer import ROIAnalyzer, plot_drawdown, plot_heatmap, plot_roi_curve, save_report_artifacts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ROI and profitability structure analysis")
    parser.add_argument("--input", "-i", default="results/backtest_full.csv", help="Main result CSV")
    parser.add_argument("--decision-log", default="logs/decisions.jsonl", help="Decision log JSONL")
    parser.add_argument("--bets-log", default="derived/bets.csv", help="Bet log CSV")
    parser.add_argument("--outdir", "-o", default="results/roi_analysis", help="Output directory")
    return parser.parse_args()


def load_optional_frame(analyzer: ROIAnalyzer, path: str) -> pd.DataFrame | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        if p.suffix.lower() == ".jsonl":
            return analyzer.load_jsonl(p)
        return analyzer.load_csv(p)
    except Exception:
        return None


def print_table(title: str, df: pd.DataFrame, limit: int = 30) -> None:
    print()
    print(f"  [{title}]")
    if df is None or len(df) == 0:
        print("    no data")
        return
    print(df.head(limit).to_string(index=False))


def main() -> None:
    args = parse_args()
    analyzer = ROIAnalyzer()

    main_df = analyzer.load_csv(args.input)
    decision_df = load_optional_frame(analyzer, args.decision_log)
    bets_df = load_optional_frame(analyzer, args.bets_log)

    report = analyzer.analyze(main_df, decision_log=decision_df, bets_log=bets_df)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    save_report_artifacts(report, outdir)

    if report.get("roi_curve") is not None:
        plot_roi_curve(report["roi_curve"], outdir / "roi_curve.png")
    if report.get("drawdown_report") is not None:
        plot_drawdown(report["drawdown_report"], outdir / "drawdown_curve.png")
    if report.get("heatmap_odds_uncertainty") is not None and len(report["heatmap_odds_uncertainty"]) > 0:
        plot_heatmap(report["heatmap_odds_uncertainty"], "Profitability Heatmap: Odds x Uncertainty", outdir / "profitability_heatmap_odds_uncertainty.png")
    if report.get("heatmap_confidence_edge") is not None and len(report["heatmap_confidence_edge"]) > 0:
        plot_heatmap(report["heatmap_confidence_edge"], "Profitability Heatmap: Confidence x Edge", outdir / "profitability_heatmap_confidence_edge.png")

    summary = report.get("overall", {})

    print()
    print("=" * 88)
    print(" ROI / Profitability Structure Report")
    print("=" * 88)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print_table("Odds ROI", report.get("odds_table", pd.DataFrame()))
    print_table("Confidence ROI", report.get("confidence_table", pd.DataFrame()))
    print_table("Edge ROI", report.get("edge_table", pd.DataFrame()))
    print_table("Uncertainty ROI", report.get("uncertainty_table", pd.DataFrame()))
    print_table("Regime ROI", report.get("regime_table", pd.DataFrame()))

    print()
    print("  [Calibration vs ROI]")
    print(json.dumps(report.get("calibration_roi", {}), ensure_ascii=False, indent=2))

    print()
    print("  [Expected EV vs Realized EV]")
    print(json.dumps(report.get("expected_vs_realized", {}), ensure_ascii=False, indent=2))

    print()
    print("  [Survival Metrics]")
    print(json.dumps(report.get("survival", {}), ensure_ascii=False, indent=2))

    print()
    print("  [Diagnostics]")
    print(json.dumps(report.get("diagnostics", {}), ensure_ascii=False, indent=2))

    print()
    print(f"  outputs saved to: {outdir}")
    print("=" * 88)


if __name__ == "__main__":
    main()
