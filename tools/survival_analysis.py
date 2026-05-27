from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.resilience_analyzer import ResilienceAnalyzer


def write_table(path: Path, frame: pd.DataFrame):
    if frame is None:
        frame = pd.DataFrame()
    frame.to_csv(path, index=False)


def main(input_csv: str, out_dir: str):
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    frame = pd.read_csv(input_csv)
    analyzer = ResilienceAnalyzer()
    result = analyzer.analyze(frame)

    write_table(out_path / "survival_curve.csv", result["baseline_curve"])
    write_table(out_path / "recovery_analysis.csv", result["recovery_analysis"])
    write_table(out_path / "stress_test_report.csv", result["stress_report"])
    write_table(out_path / "collapse_heatmap.csv", result["collapse_heatmap"])
    write_table(out_path / "aggressive_vs_defensive.csv", result["aggressive_vs_defensive"])
    write_table(out_path / "uncertainty_aware_survival.csv", result["uncertainty_aware_survival"])
    write_table(out_path / "regime_aware_survival.csv", result["regime_aware_survival"])
    write_table(out_path / "calibration_deterioration_survival.csv", result["calibration_deterioration_survival"])
    write_table(out_path / "exposure_sensitivity.csv", result["exposure_sensitivity"])

    with (out_path / "resilience_score.json").open("w", encoding="utf-8") as handle:
        json.dump(result["summary"], handle, indent=2, ensure_ascii=False)

    summary_lines = [
        "# Survival Analysis Report",
        "",
        f"- probability_of_ruin: {result['summary'].get('probability_of_ruin', 0.0):.6f}",
        f"- max_recovery_duration: {result['summary'].get('max_recovery_duration', 0)}",
        f"- stress_drawdown: {result['summary'].get('stress_drawdown', 0.0):.6f}",
        f"- exposure_collapse_risk: {result['summary'].get('exposure_collapse_risk', 0.0):.6f}",
        f"- bankroll_half_life: {result['summary'].get('bankroll_half_life', -1)}",
        f"- recovery_speed: {result['summary'].get('recovery_speed', 0.0):.6f}",
        f"- volatility_adjusted_survival: {result['summary'].get('volatility_adjusted_survival', 0.0):.6f}",
        f"- risk_adjusted_longevity: {result['summary'].get('risk_adjusted_longevity', 0.0):.6f}",
        f"- resilience_score: {result['summary'].get('resilience_score', 0.0):.2f}",
    ]
    (out_path / "report.md").write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"Wrote survival analysis reports to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="logs/bets.csv")
    parser.add_argument("--out", default="reports/survival_analysis")
    args = parser.parse_args()
    main(args.input, args.out)
