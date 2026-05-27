from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.counterfactual_common import (
    dataframe_to_markdown,
    default_policy_suite,
    load_records,
    merge_outcomes,
    policy_from_name,
    simulate_policy,
    save_summary_bundle,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate bankroll paths under counterfactual policies")
    parser.add_argument("--input", default="logs/bets.csv", help="Base log CSV/JSONL")
    parser.add_argument("--outcomes", default=None, help="Optional outcome log to merge")
    parser.add_argument("--outdir", default="results/bankroll_path", help="Output directory")
    parser.add_argument("--policy", default=None, help="Single policy name; if omitted, runs the default suite")
    parser.add_argument("--max-uncertainty", type=float, default=None, dest="max_uncertainty")
    parser.add_argument("--kelly-scale", type=float, default=None, dest="kelly_scale")
    parser.add_argument("--exposure-scale", type=float, default=None, dest="exposure_scale")
    parser.add_argument("--min-edge", type=float, default=None, dest="min_edge")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_records(args.input)
    if args.outcomes:
        df = merge_outcomes(df, load_records(args.outcomes))
    policies = [
        policy_from_name(
            args.policy,
            max_uncertainty=args.max_uncertainty,
            exposure_scale=args.exposure_scale,
            kelly_scale=args.kelly_scale,
            min_edge=args.min_edge,
        )
    ] if args.policy else default_policy_suite()

    results = [simulate_policy(df, policy) for policy in policies]
    summary_bundle = save_summary_bundle(results, outdir)

    combined = dataframe_to_markdown(results[0].path.head(30)) if results and results[0].path is not None else ""
    (outdir / "bankroll_path_preview.md").write_text(combined, encoding="utf-8")
    (outdir / "bundle_paths.json").write_text(json.dumps({key: str(value) for key, value in summary_bundle.items()}, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(results[0].summary if len(results) == 1 else "replayed default policy suite")
    logger.info("saved: %s", outdir)


if __name__ == "__main__":
    main()