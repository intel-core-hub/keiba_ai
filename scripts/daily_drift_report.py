from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.collect_drift_inputs import load_decision_rows, load_feature_snapshots, load_result_rows, parse_utc


PSI_STATUS = (
    (0.10, "stable"),
    (0.20, "watch"),
    (0.30, "warning"),
)


def population_stability_index(expected: pd.Series, actual: pd.Series, *, bins: int = 10) -> float | None:
    expected_values = pd.to_numeric(expected, errors="coerce").dropna().to_numpy(dtype=float)
    actual_values = pd.to_numeric(actual, errors="coerce").dropna().to_numpy(dtype=float)
    if len(expected_values) == 0 or len(actual_values) == 0:
        return None
    edges = np.unique(np.quantile(expected_values, np.linspace(0.0, 1.0, bins + 1)))
    if len(edges) < 3:
        min_value = min(float(np.min(expected_values)), float(np.min(actual_values)))
        max_value = max(float(np.max(expected_values)), float(np.max(actual_values)))
        if min_value == max_value:
            return 0.0
        edges = np.linspace(min_value, max_value, min(bins, 2) + 1)
    expected_counts, _ = np.histogram(expected_values, bins=edges)
    actual_counts, _ = np.histogram(actual_values, bins=edges)
    expected_pct = np.maximum(expected_counts / max(len(expected_values), 1), 1e-6)
    actual_pct = np.maximum(actual_counts / max(len(actual_values), 1), 1e-6)
    return round(float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))), 6)


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _status_for_psi(value: float | None) -> str:
    if value is None:
        return "insufficient_data"
    for threshold, label in PSI_STATUS:
        if value < threshold:
            return label
    return "severe"


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _current_window(frame: pd.DataFrame, *, days: int) -> pd.DataFrame:
    if frame.empty or "snapshot_time_utc" not in frame.columns:
        return frame
    timestamps = frame["snapshot_time_utc"].map(parse_utc)
    valid = timestamps.dropna()
    if valid.empty:
        return frame.iloc[0:0]
    cutoff = max(valid) - timedelta(days=max(days - 1, 0))
    return frame[timestamps.map(lambda item: item is not None and item >= cutoff)]


def build_daily_drift_report(
    *,
    baseline: Path,
    feature_snapshots: Path,
    decision_log: Path,
    results: Path,
    outdir: Path,
    top_features: list[str],
    days: int = 7,
) -> dict[str, Any]:
    baseline_df = pd.read_csv(baseline, low_memory=False) if baseline.exists() else pd.DataFrame()
    snapshot_rows = load_feature_snapshots(feature_snapshots)
    snapshot_df = pd.DataFrame(snapshot_rows)
    current_df = _current_window(snapshot_df, days=days)

    if not top_features:
        shared = [column for column in baseline_df.columns if column in current_df.columns]
        top_features = [column for column in shared if pd.api.types.is_numeric_dtype(baseline_df[column])][:5]

    summary_rows: list[dict[str, Any]] = []
    for feature in top_features:
        if current_df.empty or feature not in current_df.columns:
            continue
        values = pd.to_numeric(current_df[feature], errors="coerce")
        dates = current_df["snapshot_time_utc"].map(lambda value: (parse_utc(value) or parse_utc("1970-01-01T00:00:00+00:00")).date().isoformat())
        for day in sorted(set(dates)):
            day_values = values[dates == day].dropna()
            if day_values.empty:
                continue
            summary_rows.append(
                {
                    "date": day,
                    "feature": feature,
                    "count": int(day_values.count()),
                    "mean": float(day_values.mean()),
                    "std": float(day_values.std()) if len(day_values) > 1 else 0.0,
                    "min": float(day_values.min()),
                    "max": float(day_values.max()),
                }
            )

    psi_rows: list[dict[str, Any]] = []
    for feature in top_features:
        baseline_values = _numeric(baseline_df, feature)
        current_values = _numeric(current_df, feature)
        psi = None
        if not baseline_values.empty and not current_values.empty:
            psi = population_stability_index(baseline_values, current_values)
        psi_rows.append(
            {
                "feature": feature,
                "psi": "" if psi is None else psi,
                "status": _status_for_psi(psi),
                "baseline_count": int(len(baseline_values)),
                "current_count": int(len(current_values)),
            }
        )

    decision_rows = load_decision_rows(decision_log)
    result_rows = load_result_rows(results)
    result_keys = {(row.get("race_id", ""), row.get("horse_id", "")) for row in result_rows}
    by_date: dict[str, dict[str, int]] = defaultdict(lambda: {"decisions": 0, "results": 0, "joined_rows": 0})
    for row in decision_rows:
        ts = parse_utc(row.get("occurred_at_utc"))
        day = ts.date().isoformat() if ts else "UNKNOWN"
        by_date[day]["decisions"] += 1
        if (row.get("race_id", ""), row.get("horse_id", "")) in result_keys:
            by_date[day]["joined_rows"] += 1
    for row in result_rows:
        ts = parse_utc(row.get("result_time"))
        day = ts.date().isoformat() if ts else "UNKNOWN"
        by_date[day]["results"] += 1
    prediction_rows = [{"date": day, **counts} for day, counts in sorted(by_date.items())]

    _write_csv(outdir / "daily_feature_summary.csv", summary_rows, ["date", "feature", "count", "mean", "std", "min", "max"])
    _write_csv(outdir / "daily_feature_psi.csv", psi_rows, ["feature", "psi", "status", "baseline_count", "current_count"])
    _write_csv(outdir / "daily_prediction_summary.csv", prediction_rows, ["date", "decisions", "results", "joined_rows"])

    statuses = {row["status"] for row in psi_rows}
    report = {
        "passed": bool(psi_rows) and "insufficient_data" not in statuses and "severe" not in statuses,
        "status": "insufficient_data" if not psi_rows or "insufficient_data" in statuses else ("severe" if "severe" in statuses else "ok"),
        "baseline_rows": int(len(baseline_df)),
        "current_rows": int(len(current_df)),
        "features": top_features,
        "outputs": {
            "daily_feature_summary": str(outdir / "daily_feature_summary.csv"),
            "daily_feature_psi": str(outdir / "daily_feature_psi.csv"),
            "daily_prediction_summary": str(outdir / "daily_prediction_summary.csv"),
        },
    }
    (outdir / "daily_drift_status.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate daily drift inputs and PSI report")
    parser.add_argument("--baseline", default="data/processed/historical_dataset.csv")
    parser.add_argument("--feature-snapshots", default="data/feature_snapshots")
    parser.add_argument("--decision-log", default="logs/decisions.jsonl")
    parser.add_argument("--results", default="data/results/race_results.csv")
    parser.add_argument("--outdir", default="reports/drift")
    parser.add_argument("--top-features", default="")
    parser.add_argument("--days", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    features = [item.strip() for item in args.top_features.split(",") if item.strip()]
    report = build_daily_drift_report(
        baseline=Path(args.baseline),
        feature_snapshots=Path(args.feature_snapshots),
        decision_log=Path(args.decision_log),
        results=Path(args.results),
        outdir=Path(args.outdir),
        top_features=features,
        days=args.days,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
