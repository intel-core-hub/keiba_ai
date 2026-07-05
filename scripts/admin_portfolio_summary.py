#!/usr/bin/env python
"""Offline admin portfolio summary.

Usage:
    python scripts/admin_portfolio_summary.py --bets-log derived/bets.csv
    python scripts/admin_portfolio_summary.py --monte-carlo --bets-log derived/bets.csv

This script intentionally uses pandas/numpy and is offline-only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import numpy as np


def portfolio_summary(path: str) -> int:
    p = Path(path)
    if not p.exists():
        print(f"{path} not found")
        return 1
    df = pd.read_csv(p)
    print("bets_logged", len(df))
    if len(df) == 0:
        return 0
    ev_col = None
    for name in ("expected_value_per_unit", "ev"):
        if name in df.columns:
            ev_col = name
            break
    if ev_col:
        print("mean_ev", float(df[ev_col].astype(float).mean()))
    if "brier" in df.columns:
        print("brier", float(df["brier"].astype(float).mean()))
    if "ece" in df.columns:
        print("ece", float(df["ece"].astype(float).mean()))
    return 0


def monte_carlo_check(path: str) -> int:
    p = Path(path)
    if not p.exists():
        print(f"{path} not found")
        return 1
    df = pd.read_csv(p)
    probs = df["probability"].astype(float).tolist() if "probability" in df.columns else []
    odds = df["odds"].astype(float).tolist() if "odds" in df.columns else []
    stakes = df["stake"].astype(float).tolist() if "stake" in df.columns else []
    print("probs_len", len(probs))
    if probs:
        print("prob_mean", float(np.mean(probs)))
        print("prob_std", float(np.std(probs)))
    if odds:
        print("odds_mean", float(np.mean(odds)))
    if stakes:
        print("stakes_mean", float(np.mean(stakes)))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bets-log", default="derived/bets.csv")
    parser.add_argument("--monte-carlo", action="store_true")
    args = parser.parse_args()
    if args.monte_carlo:
        return monte_carlo_check(args.bets_log)
    return portfolio_summary(args.bets_log)


if __name__ == "__main__":
    raise SystemExit(main())
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


def portfolio_summary(bets_log: str = "derived/bets.csv") -> None:
    path = Path(bets_log)
    if not path.exists():
        print("bets log not found:", bets_log)
        return
    df = pd.read_csv(path)
    print({"bets_logged": len(df)})


def monte_carlo_check(bets_log: str = "derived/bets.csv") -> None:
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
    parser.add_argument("--bets-log", default="derived/bets.csv")
    args = parser.parse_args()

    if args.summary:
        portfolio_summary(args.bets_log)
    elif args.monte_carlo:
        monte_carlo_check(args.bets_log)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
