from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_latency_regression(
    *,
    current_path: Path,
    previous_path: Path | None = None,
    threshold_p99: float = 200.0,
    threshold_p999: float = 250.0,
    max_regression_pct: float = 30.0,
) -> dict[str, Any]:
    current = _load(current_path)
    previous = _load(previous_path) if previous_path and previous_path.exists() else {}
    current_p99 = _number(current.get("p99"))
    current_p999 = _number(current.get("p999"))
    baseline_p99 = (
        _number(current.get("baseline_p99"))
        or _number(previous.get("baseline_p99"))
        or _number(previous.get("p99"))
    )
    previous_p999 = _number(previous.get("p999"))
    timeout_rate = _number(current.get("timeout_rate"))
    latency_regression_rate = None
    if current_p99 is not None and baseline_p99 is not None and baseline_p99 > 0:
        latency_regression_rate = (current_p99 / baseline_p99) - 1.0

    failures: list[str] = []
    if current_p99 is None:
        failures.append("p99 missing")
    elif current_p99 >= threshold_p99:
        failures.append("p99 above threshold")
    if current_p999 is None:
        failures.append("p999 missing")
    elif current_p999 >= threshold_p999:
        failures.append("p999 above threshold")
    if timeout_rate is None:
        failures.append("timeout_rate missing")
    elif timeout_rate > 0:
        failures.append("timeout_rate > 0")
    if latency_regression_rate is not None and latency_regression_rate >= (max_regression_pct / 100.0):
        failures.append("p99 regression >= 30%")

    return {
        "passed": not failures,
        "failures": failures,
        "baseline_p99": baseline_p99,
        "current_p99": current_p99,
        "current_p999": current_p999,
        "previous_p999": previous_p999,
        "latency_regression_rate": (
            round(latency_regression_rate, 6) if latency_regression_rate is not None else None
        ),
        "latency_regression_pct": (
            round(latency_regression_rate * 100.0, 4) if latency_regression_rate is not None else None
        ),
        "delta_pct": round(latency_regression_rate * 100.0, 4) if latency_regression_rate is not None else None,
        "timeout_rate": timeout_rate,
        "threshold_p99": threshold_p99,
        "threshold_p999": threshold_p999,
        "max_regression_pct": max_regression_pct,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Stage 4 latency tail regression")
    parser.add_argument("--current", default=".ci_latency.json")
    parser.add_argument("--previous", default=None)
    parser.add_argument("--threshold-p99", type=float, default=200.0)
    parser.add_argument("--threshold-p999", type=float, default=250.0)
    parser.add_argument("--max-regression-pct", type=float, default=30.0)
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = evaluate_latency_regression(
        current_path=Path(args.current),
        previous_path=Path(args.previous) if args.previous else None,
        threshold_p99=args.threshold_p99,
        threshold_p999=args.threshold_p999,
        max_regression_pct=args.max_regression_pct,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
