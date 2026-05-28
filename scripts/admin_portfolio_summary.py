#!/usr/bin/env python
"""Offline admin utilities for portfolio and monte-carlo diagnostics.

This file contains the code extracted from main.py that used Pandas.
Run locally as an offline tool; do NOT import from runtime core modules.

Usage:
    python scripts/admin_portfolio_summary.py --summary
    python scripts/admin_portfolio_summary.py --monte-carlo
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

try:
    import pandas as pd
except Exception as e:
    raise RuntimeError("pandas is required for admin_portfolio_summary.py") from e


def portfolio_summary(bets_log: str = "logs/bets.csv") -> None:
    path = Path(bets_log)
    if not path.exists():
        print("bets log not found:", bets_log)
        return
    df = pd.read_csv(path)
    print({"bets_logged": len(df)})


def monte_carlo_check(bets_log: str = "logs/bets.csv") -> None:
    path = Path(bets_log)
    if not path.exists():
        print("bets log not found:", bets_log)
        return
    df = pd.read_csv(path)
    probs = df.get("probability", pd.Series()).astype(float).tolist()
    odds = df.get("odds", pd.Series()).astype(float).tolist()
    stakes = df.get("stake", pd.Series()).astype(float).tolist()
    print({
        "n": len(probs),
        "prob_mean": float(pd.Series(probs).mean()) if len(probs) else None,
        "odds_mean": float(pd.Series(odds).mean()) if len(odds) else None,
        "stakes_mean": float(pd.Series(stakes).mean()) if len(stakes) else None,
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--monte-carlo", action="store_true")
    parser.add_argument("--bets-log", default="logs/bets.csv")
    args = parser.parse_args()

    if args.summary:
        portfolio_summary(args.bets_log)
    elif args.monte_carlo:
        monte_carlo_check(args.bets_log)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
