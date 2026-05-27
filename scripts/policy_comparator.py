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
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare counterfactual policies")
    parser.add_argument("--input", default="logs/bets.csv", help="Base log CSV/JSONL")
    parser.add_argument("--outdir", default="results/policy_comparison", help="Output directory")
    parser.add_argument("--policy", action="append", dest="policies", default=None, help="Specific policy to run; can be repeated")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_records(args.input)
    if args.policies is None:
        selected_names = None
    else:
        selected_names = set(args.policies)
    if args.policies:
        policies = [p for p in default_policy_suite() if p.name in selected_names]
        if not policies:
            raise SystemExit("No matching policies requested")
    else:
        policies = default_policy_suite()

    results = [simulate_policy(df, policy) for policy in policies]
    summary = compare_summaries(results)
    exposure = exposure_heatmap_frame(results)
    save_summary_bundle(results, outdir)

    summary.to_csv(outdir / "policy_comparison.csv", index=False, encoding="utf-8-sig")
    exposure.to_csv(outdir / "policy_exposure.csv", index=False, encoding="utf-8-sig")

    report = {
        "input": args.input,
        "policies": [result.summary for result in results],
        "aggressive_vs_defensive": {
            "aggressive": summary[summary["policy"] == "aggressive"].to_dict(orient="records"),
            "defensive": summary[summary["policy"] == "defensive"].to_dict(orient="records"),
        },
    }
    (outdir / "policy_comparison_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print()
    cols = [column for column in ["policy", "roi", "risk_adjusted_roi", "max_drawdown", "ruin_probability", "survival_score", "stability_improvement", "collapse_avoidance"] if column in summary.columns]
    if cols:
        print(summary[cols].to_string(index=False))
    logger.info("saved: %s", outdir)


if __name__ == "__main__":
    main()