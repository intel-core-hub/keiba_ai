"""
Simple leakage/audit scanner for processed dataset
- Reports suspicious column names (final_odds, closing_odds, payout, avg_finish_last5, etc.)
- Checks whether numeric columns were globally filled (heuristic: no NaNs)
- Emits a small CSV report

Usage:
    python scripts/audit_raw_features.py data/processed/historical_dataset.csv

"""
import sys
import pandas as pd
import re

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python scripts/audit_raw_features.py <processed_csv>')
        sys.exit(1)

    path = sys.argv[1]
    df = pd.read_csv(path)

    suspicious_keywords = [
        'final_odds', 'closing_odds', 'payout', 'popularity', 'pop', 'post_race', 'future', 'avg_finish_last5', 'avg_speed_index_last5'
    ]

    found = [c for c in df.columns if any(k in c.lower() for k in suspicious_keywords)]

    numeric = df.select_dtypes(include=['number']).columns
    numeric_na = {c: int(df[c].isna().sum()) for c in numeric}

    with open('reports/audit_raw_features.txt', 'w', encoding='utf-8') as f:
        f.write('suspicious_columns:\n')
        for c in found:
            f.write(f'- {c}\n')
        f.write('\nnumeric_na_counts:\n')
        for c, n in numeric_na.items():
            f.write(f'- {c}: {n}\n')

    print('Audit written to reports/audit_raw_features.txt')
