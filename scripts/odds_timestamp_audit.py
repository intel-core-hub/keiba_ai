"""CLI audit for odds timestamp leakage.

This script is intentionally conservative: if a dataset only exposes plain
odds / favorite_rank columns without timing metadata, it will flag the
data as ambiguous instead of silently treating it as safe.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.audit import OddsTimestampValidator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit odds timestamps for leakage")
    parser.add_argument("--input", required=True, help="CSV path to audit")
    parser.add_argument("--outdir", default="results/odds_timestamp_audit", help="Output directory")
    parser.add_argument("--race-start-col", default=None, dest="race_start_col")
    parser.add_argument("--bet-time-col", default=None, dest="bet_time_col")
    parser.add_argument("--odds-col", default="odds", dest="odds_col")
    parser.add_argument("--favorite-rank-col", default="favorite_rank", dest="favorite_rank_col")
    parser.add_argument("--plain-odds-snapshot-label", default=None, dest="plain_odds_snapshot_label")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if str(args.input).lower().endswith(".jsonl"):
        df = pd.read_json(args.input, lines=True)
    else:
        df = pd.read_csv(args.input, low_memory=False)
    validator = OddsTimestampValidator(strict=True)
    report = validator.validate(
        df,
        race_start_col=args.race_start_col,
        bet_time_col=args.bet_time_col,
        odds_col=args.odds_col,
        favorite_rank_col=args.favorite_rank_col,
        plain_odds_snapshot_label=args.plain_odds_snapshot_label,
    )

    annotated = report.pop("annotated_frame")
    report_path = outdir / "odds_timestamp_report.json"
    rows_path = outdir / "odds_timestamp_rows.csv"

    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    annotated.to_csv(rows_path, index=False, encoding="utf-8-sig")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"saved: {report_path}")
    print(f"saved: {rows_path}")


if __name__ == "__main__":
    main()