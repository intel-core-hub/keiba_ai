from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.counterfactual_common import (
    compare_summaries,
    default_policy_suite,
    exposure_heatmap_frame,
    load_records,
    merge_outcomes,
    save_summary_bundle,
    simulate_policy,
    bankroll_curve_frame,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Counterfactual replay system")
    parser.add_argument("--input", default="logs/bets.csv", help="Base log CSV/JSONL")
    parser.add_argument("--outcomes", default=None, help="Optional outcome log to merge")
    parser.add_argument("--outdir", default="results/counterfactual_replay", help="Output directory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_records(args.input)
    if args.outcomes:
        df = merge_outcomes(df, load_records(args.outcomes))
    results = [simulate_policy(df, policy) for policy in default_policy_suite()]

    compare_df = compare_summaries(results)
    curves_df = bankroll_curve_frame(results)
    exposure_df = exposure_heatmap_frame(results)

    compare_df.to_csv(outdir / "counterfactual_comparison.csv", index=False, encoding="utf-8-sig")
    curves_df.to_csv(outdir / "bankroll_curves.csv", index=False, encoding="utf-8-sig")
    exposure_df.to_csv(outdir / "exposure_heatmap.csv", index=False, encoding="utf-8-sig")
    save_summary_bundle(results, outdir)

    (outdir / "counterfactual_report.json").write_text(json.dumps({
        "input": args.input,
        "policies": [result.summary for result in results],
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print()
    print(compare_df[[column for column in ["policy", "roi", "risk_adjusted_roi", "max_drawdown", "ruin_probability", "survival_score", "stability_improvement"] if column in compare_df.columns]].to_string(index=False))
    logger.info("saved: %s", outdir)


if __name__ == "__main__":
    main()