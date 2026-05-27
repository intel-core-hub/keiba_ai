"""Simple uncertainty drift monitor.

Reads a decision log CSV with `uncertainty_score` and `timestamp`/`race_datetime` and computes
rolling statistics and flags sustained increases.

Usage:
  python scripts/uncertainty_monitor.py --input results/decision_log.csv --out results/uncertainty_drift.json
"""
import argparse
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd


def monitor(df: pd.DataFrame, window: int = 100, step: int = 20, alert_delta: float = 0.05):
    # ensure order by time if available
    time_cols = [c for c in ['race_datetime', 'timestamp', 'date', 'datetime'] if c in df.columns]
    if time_cols:
        df = df.sort_values(time_cols[0])

    if 'uncertainty_score' not in df.columns:
        if 'pred_prob' in df.columns:
            try:
                from learning.uncertainty import normalized_entropy

                df['uncertainty_score'] = df['pred_prob'].fillna(0.0).apply(lambda p: normalized_entropy(float(p)))
            except Exception:
                df['uncertainty_score'] = df['pred_prob'].fillna(0.0)
        else:
            df['uncertainty_score'] = 0.5
    u = df['uncertainty_score'].fillna(0.0).to_numpy()
    n = len(u)
    if n == 0:
        return {}

    rolling_means = []
    for i in range(0, max(1, n - window + 1), step):
        segment = u[i:i+window]
        rolling_means.append(float(np.mean(segment)))

    alert = False
    message = ''
    if len(rolling_means) >= 3:
        if rolling_means[-1] - min(rolling_means[:-1]) > alert_delta:
            alert = True
            message = f'Uncertainty drift detected: last mean {rolling_means[-1]:.3f} vs min prior {min(rolling_means[:-1]):.3f}'

    return {
        'n': n,
        'rolling_means': rolling_means,
        'alert': alert,
        'message': message,
        'overall_mean': float(np.mean(u)),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', '-i', required=True)
    p.add_argument('--out', '-o', default='results/uncertainty_drift.json')
    args = p.parse_args()

    df = pd.read_csv(args.input, low_memory=False)
    res = monitor(df)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w') as f:
        json.dump(res, f, indent=2)
    print('Wrote', args.out)


if __name__ == '__main__':
    main()
