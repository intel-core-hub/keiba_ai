from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], *, timeout_seconds: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "args": args,
            "returncode": None,
            "passed": False,
            "stdout": ((exc.stdout or "") if isinstance(exc.stdout, str) else "")[-4000:],
            "stderr": f"step timed out after {timeout_seconds:g} seconds",
            "timeout_seconds": timeout_seconds,
        }
    stdout = completed.stdout or ""
    passed = completed.returncode == 0
    parsed_stdout = _parse_json_stdout(stdout)
    if isinstance(parsed_stdout, dict) and parsed_stdout.get("passed") is False:
        passed = False

    result = {
        "args": args,
        "returncode": completed.returncode,
        "passed": passed,
        "stdout": stdout[-4000:],
        "stderr": (completed.stderr or "")[-4000:],
    }
    if isinstance(parsed_stdout, dict) and "passed" in parsed_stdout:
        result["reported_passed"] = parsed_stdout.get("passed")
    if isinstance(parsed_stdout, dict) and parsed_stdout.get("status"):
        result["reported_status"] = parsed_stdout.get("status")
    return result


def _parse_json_stdout(stdout: str) -> Any:
    text = stdout.strip()
    if not text or not text.startswith("{"):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_daily_update(args: argparse.Namespace) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    common = [sys.executable, "-m"]
    provider_config = getattr(args, "provider_config", None)
    step_timeout_seconds = float(getattr(args, "step_timeout_seconds", 300.0))
    snapshot_cmd = [
        *common,
        "scripts.collect_market_snapshots",
        "--provider",
        args.provider,
        "--schedule",
        args.schedule,
        "--odds-dir",
        args.odds_dir,
        "--early-output",
        args.early_output,
        "--closing-output",
        args.closing_output,
        "--status",
        args.collection_status,
        "--errors",
        args.collection_errors,
    ]
    if provider_config:
        snapshot_cmd.extend(["--provider-config", provider_config])
    if args.now:
        snapshot_cmd.extend(["--now", args.now])
    steps.append({"name": "collect_market_snapshots", **_run(snapshot_cmd, timeout_seconds=step_timeout_seconds)})

    result_cmd = [
        *common,
        "scripts.collect_race_results",
        "--provider",
        args.provider,
        "--schedule",
        args.schedule,
        "--results-dir",
        args.results_dir,
        "--output",
        args.results_output,
        "--status",
        args.result_status,
        "--errors",
        args.result_errors,
    ]
    if provider_config:
        result_cmd.extend(["--provider-config", provider_config])
    if args.now:
        result_cmd.extend(["--now", args.now])
    steps.append({"name": "collect_race_results", **_run(result_cmd, timeout_seconds=step_timeout_seconds)})

    steps.append(
        {
            "name": "daily_drift_report",
            **_run(
                [
                    *common,
                    "scripts.daily_drift_report",
                    "--baseline",
                    args.baseline,
                    "--feature-snapshots",
                    args.feature_snapshots,
                    "--decision-log",
                    args.decision_log,
                    "--results",
                    args.results_output,
                    "--outdir",
                    args.drift_outdir,
                    "--top-features",
                    args.top_features,
                ],
                timeout_seconds=step_timeout_seconds,
            ),
        }
    )

    steps.append(
        {
            "name": "derive_bets_csv_from_decisions",
            **_run(
                [
                    *common,
                    "scripts.derive_bets_csv_from_decisions",
                    "--jsonl",
                    args.decision_log,
                    "--csv",
                    args.derived_bets,
                ],
                timeout_seconds=step_timeout_seconds,
            ),
        }
    )

    steps.append(
        {
            "name": "stage4_current_update",
            **_run(
                [
                    *common,
                    "scripts.stage4_current_update",
                    "--decision-log",
                    args.decision_log,
                    "--derived-bets",
                    args.derived_bets,
                    "--early-snapshot",
                    args.early_output,
                    "--closing-snapshot",
                    args.closing_output,
                    "--base-historical",
                    args.baseline,
                ],
                timeout_seconds=step_timeout_seconds,
            ),
        }
    )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": all(step["passed"] for step in steps),
        "steps": steps,
    }
    status_path = Path(args.status)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the daily real-data evidence update")
    parser.add_argument("--provider", choices=("local_file", "http"), default="local_file")
    parser.add_argument("--provider-config", default="config/real_data_provider.yaml")
    parser.add_argument("--schedule", default="data/live_inputs/today_races.json")
    parser.add_argument("--odds-dir", default="data/live_inputs/odds")
    parser.add_argument("--results-dir", default="data/live_inputs/results")
    parser.add_argument("--baseline", default="data/processed/historical_dataset.csv")
    parser.add_argument("--decision-log", default="logs/decisions.jsonl")
    parser.add_argument("--derived-bets", default="derived/bets.csv")
    parser.add_argument("--feature-snapshots", default="data/feature_snapshots")
    parser.add_argument("--early-output", default="data/market_snapshots/early_odds.csv")
    parser.add_argument("--closing-output", default="data/market_snapshots/closing_odds.csv")
    parser.add_argument("--results-output", default="data/results/race_results.csv")
    parser.add_argument("--collection-status", default="reports/data_collection/collection_status.json")
    parser.add_argument("--collection-errors", default="reports/data_collection/collection_errors.jsonl")
    parser.add_argument("--result-status", default="reports/data_collection/result_status.json")
    parser.add_argument("--result-errors", default="reports/data_collection/result_errors.jsonl")
    parser.add_argument("--drift-outdir", default="reports/drift")
    parser.add_argument("--top-features", default="odds_value,favorite_rank,distance,market_support,track_affinity")
    parser.add_argument("--status", default="reports/data_collection/daily_update_status.json")
    parser.add_argument("--now", default=None, help="UTC ISO8601 override for deterministic runs")
    parser.add_argument("--step-timeout-seconds", type=float, default=300.0)
    return parser.parse_args()


def main() -> int:
    report = run_daily_update(parse_args())
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
