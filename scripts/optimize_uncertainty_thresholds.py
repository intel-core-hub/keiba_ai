"""Optimize uncertainty thresholds by scanning historical backtest CSV.

Reads a CSV containing at least: `uncertainty_score`, `pnl`, `stake` (or assumes unit stake).
For each threshold candidate it computes ROI, hit rate, and simple drawdown metric.

Usage:
  python scripts/optimize_uncertainty_thresholds.py --input results/backtest_full.csv --out results/uncertainty_thresholds.csv
"""
import argparse
import csv
import math
import os
from typing import List

import numpy as np
import pandas as pd


def evaluate_threshold(df: pd.DataFrame, threshold: float):
    # skip bets with uncertainty_score > threshold
    if 'uncertainty_score' not in df.columns:
        # fallback: estimate uncertainty by normalized entropy of predicted probability
        if 'pred_prob' in df.columns:
            try:
                from learning.uncertainty import normalized_entropy

                df = df.copy()
                df['uncertainty_score'] = df['pred_prob'].fillna(0.0).apply(lambda p: normalized_entropy(float(p)))
            except Exception:
                df = df.copy()
                df['uncertainty_score'] = 0.5
        else:
            raise RuntimeError('uncertainty_score and pred_prob columns missing')

    sub = df[df['uncertainty_score'] <= threshold].copy()
    if sub.empty:
        return {'threshold': threshold, 'n': 0, 'roi': float('nan'), 'hit_rate': float('nan'), 'max_drawdown': float('nan')}

    stake_col = 'stake' if 'stake' in sub.columns else None
    if stake_col is None:
        sub['__stake__'] = 1.0
        stake_col = '__stake__'

    total_stake = sub[stake_col].sum()
    total_pnl = sub['pnl'].sum() if 'pnl' in sub.columns else (sub.get('profit', sub.get('profit_loss', pd.Series([0]*len(sub)))).sum())
    roi = total_pnl / total_stake if total_stake > 0 else float('nan')
    hit_rate = (sub['pnl'] > 0).sum() / len(sub)

    # drawdown
    cum = sub['pnl'].fillna(0).cumsum()
    peak = cum.cummax()
    drawdown = cum - peak
    max_dd = float(drawdown.min())

    return {'threshold': threshold, 'n': len(sub), 'roi': roi, 'hit_rate': hit_rate, 'max_drawdown': max_dd}


def scan_thresholds(df: pd.DataFrame, thresholds: List[float]):
    rows = []
    for t in thresholds:
        rows.append(evaluate_threshold(df, float(t)))
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', '-i', required=True)
    p.add_argument('--out', '-o', default='results/uncertainty_thresholds.csv')
    p.add_argument('--min', type=float, default=0.0)
    p.add_argument('--max', type=float, default=1.0)
    p.add_argument('--steps', type=int, default=21)
    args = p.parse_args()

    # try to read only needed cols to avoid C-engine OOM on very large CSVs
    usecols = None
    sample = pd.read_csv(args.input, nrows=5, engine='python')
    potential = set(sample.columns)
    required = set(['pred_prob', 'uncertainty_score', 'pnl', 'stake'])
    usecols = [c for c in ['uncertainty_score', 'pred_prob', 'pnl', 'stake'] if c in potential]
    if usecols:
        df = pd.read_csv(args.input, usecols=usecols, engine='python')
    else:
        df = pd.read_csv(args.input, engine='python')
    thresholds = list(np.linspace(args.min, args.max, args.steps))
    results = scan_thresholds(df, thresholds)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    results.to_csv(args.out, index=False)
    print('Wrote', args.out)


if __name__ == '__main__':
    main()
