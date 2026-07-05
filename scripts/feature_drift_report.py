from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_attribution_utils import IDENTIFIER_COLUMNS, PREDICTOR_FEATURES, TARGET_COLUMNS


PSI_A_THRESHOLD = 0.20
PSI_S_THRESHOLD = 0.10


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def population_stability_index(expected: pd.Series, actual: pd.Series, *, bins: int = 10) -> float | None:
    expected_values = pd.to_numeric(expected, errors="coerce").dropna().to_numpy(dtype=float)
    actual_values = pd.to_numeric(actual, errors="coerce").dropna().to_numpy(dtype=float)
    if len(expected_values) == 0 or len(actual_values) == 0:
        return None

    quantiles = np.linspace(0.0, 1.0, bins + 1)
    edges = np.unique(np.quantile(expected_values, quantiles))
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


def candidate_feature_columns(baseline: pd.DataFrame, current: pd.DataFrame, *, top_n: int) -> list[str]:
    shared = [column for column in PREDICTOR_FEATURES if column in baseline.columns and column in current.columns]
    if len(shared) >= top_n:
        return shared[:top_n]

    excluded = IDENTIFIER_COLUMNS | TARGET_COLUMNS
    for column in baseline.columns:
        if column in shared or column in excluded or column not in current.columns:
            continue
        if pd.api.types.is_numeric_dtype(baseline[column]) or pd.api.types.is_numeric_dtype(current[column]):
            shared.append(column)
        if len(shared) >= top_n:
            break
    return shared[:top_n]


def build_feature_drift_report(
    *,
    baseline_path: Path,
    current_path: Path,
    output_path: Path,
    top_n: int = 5,
    bins: int = 10,
) -> dict[str, Any]:
    baseline = pd.read_csv(baseline_path, low_memory=False)
    current = pd.read_csv(current_path, low_memory=False)
    features = candidate_feature_columns(baseline, current, top_n=top_n)

    psi: dict[str, float | None] = {}
    for column in features:
        psi[column] = population_stability_index(
            _numeric_series(baseline, column),
            _numeric_series(current, column),
            bins=bins,
        )

    odds_psi = None
    if "odds" in baseline.columns and "odds" in current.columns:
        odds_psi = population_stability_index(
            _numeric_series(baseline, "odds"),
            _numeric_series(current, "odds"),
            bins=bins,
        )
        psi["odds_distribution"] = odds_psi

    valid_values = [value for value in psi.values() if value is not None]
    over_a = [column for column, value in psi.items() if value is not None and value >= PSI_A_THRESHOLD]
    report = {
        "passed": len(over_a) == 0,
        "top_features": features,
        "psi": psi,
        "odds_distribution_psi": odds_psi,
        "max_psi": max(valid_values) if valid_values else None,
        "thresholds": {
            "S_all_psi_below": PSI_S_THRESHOLD,
            "A_all_psi_below": PSI_A_THRESHOLD,
        },
        "a7_3_status": "A_or_better" if not over_a else "B_or_C_review_required",
        "psi_over_threshold": over_a,
        "baseline_rows": int(len(baseline)),
        "current_rows": int(len(current)),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build A7-3 feature drift PSI report")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--output", default="reports/stage4/feature_drift_report.json")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--bins", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_feature_drift_report(
        baseline_path=Path(args.baseline),
        current_path=Path(args.current),
        output_path=Path(args.output),
        top_n=args.top_n,
        bins=args.bins,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
