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
    parser = argparse.ArgumentParser(description="Run a single counterfactual policy replay")
    parser.add_argument("--input", default="logs/decisions.jsonl", help="Canonical decision JSONL")
    parser.add_argument("--outcomes", default=None, help="Optional outcome log to merge by race/selection")
    parser.add_argument("--policy", default="recorded", help="Policy name (recorded/no_bet/kelly_half/aggressive/defensive/regime_no_bet/calibration_stop/uncertainty_threshold)")
    parser.add_argument("--outdir", default="results/counterfactual_replay/single_policy", help="Output directory")
    parser.add_argument("--max-uncertainty", type=float, default=None, dest="max_uncertainty")
    parser.add_argument("--kelly-scale", type=float, default=None, dest="kelly_scale")
    parser.add_argument("--exposure-scale", type=float, default=None, dest="exposure_scale")
    parser.add_argument("--min-edge", type=float, default=None, dest="min_edge")
    parser.add_argument("--calibration-window", type=int, default=20, dest="calibration_window")
    parser.add_argument("--calibration-delta", type=float, default=0.04, dest="calibration_delta")
    parser.add_argument("--calibration-ratio", type=float, default=1.10, dest="calibration_ratio")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_records(args.input)
    if args.outcomes:
        df = merge_outcomes(df, load_records(args.outcomes))

    policy = policy_from_name(
        args.policy,
        max_uncertainty=args.max_uncertainty,
        calibration_window=args.calibration_window,
        calibration_delta=args.calibration_delta,
        calibration_ratio=args.calibration_ratio,
        exposure_scale=args.exposure_scale,
        kelly_scale=args.kelly_scale,
        min_edge=args.min_edge,
    )

    result = simulate_policy(df, policy)
    result.path.to_csv(outdir / "policy_path.csv", index=False, encoding="utf-8-sig")
    (outdir / "policy_summary.json").write_text(json.dumps(result.summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    save_summary_bundle([result], outdir)

    print()
    print(json.dumps(result.summary, ensure_ascii=False, indent=2))
    logger.info("saved: %s", outdir)


if __name__ == "__main__":
    main()
