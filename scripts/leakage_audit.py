import argparse
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.audit.leakage_auditor import LeakageAuditor, save_report


def load_input(path: str) -> pd.DataFrame:
    if path.endswith(".csv"):
        return pd.read_csv(path, parse_dates=True)
    if path.endswith(".jsonl") or path.endswith(".ndjson"):
        return pd.read_json(path, lines=True)
    if path.endswith(".parquet"):
        return pd.read_parquet(path)
    raise ValueError("unsupported file format: %s" % path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--timestamp-col", default="timestamp")
    p.add_argument("--fold-col", default=None)
    p.add_argument("--target-col", default=None)
    p.add_argument("--outdir", default="results/leakage_audit")
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    df = load_input(args.input)
    # ensure timestamp col is datetime
    if args.timestamp_col in df.columns:
        df[args.timestamp_col] = pd.to_datetime(df[args.timestamp_col])

    auditor = LeakageAuditor(df, timestamp_col=args.timestamp_col, fold_col=args.fold_col, target_col=args.target_col)
    report, suspects_df = auditor.audit()

    report_path = os.path.join(args.outdir, "leakage_report.json")
    save_report(report, report_path)
    rows_path = os.path.join(args.outdir, "suspicious_rows.csv")
    suspects_df.to_csv(rows_path, index=False)
    print(json.dumps({"status": "done", "report": report_path, "suspicious_rows": rows_path}))


if __name__ == "__main__":
    main()
