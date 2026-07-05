from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.replay.historical_snapshot_loader import HistoricalSnapshotLoader
from core.replay.replay_engine import ReplayEngine
from scripts.derive_bets_csv_from_decisions import derive as derive_bets_csv
from scripts.stage4_evidence_blockers_report import build_blockers_report
from scripts.stage4_rehearsal_evidence import _preflight_report
from scripts.stage4_rubric_v2_2_report import build_report as build_rubric_report
from scripts.stage4_survivability_report import build_report as build_survivability_report


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _run(args: list[str], *, expected_failure: bool = False) -> dict[str, Any]:
    completed = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace")
    passed = completed.returncode == 0 or expected_failure
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    return {
        "args": args,
        "returncode": completed.returncode,
        "passed": passed,
        "expected_failure": expected_failure,
        "stdout": stdout[-4000:],
        "stderr": stderr[-4000:],
    }


def _snapshot_report_ready(path: Path) -> bool:
    report = _load_json(path.with_suffix(path.suffix + ".market_snapshot_report.json"))
    early = report.get("early", {})
    closing = report.get("closing", {})
    return (
        path.exists()
        and early.get("merged") is True
        and closing.get("merged") is True
        and int(early.get("matched_rows", 0) or 0) > 0
        and int(closing.get("matched_rows", 0) or 0) > 0
    )


def _market_outputs_exist(outdir: Path) -> bool:
    return all(
        (outdir / name).exists()
        for name in (
            "variant_summary.csv",
            "odds_regime_summary.csv",
            "race_class_summary.csv",
            "odds_perturbation_summary.csv",
        )
    )


def _jsonable_market_plan(plan: dict[str, Any]) -> dict[str, Any]:
    out = dict(plan)
    if isinstance(out.get("input"), Path):
        out["input"] = str(out["input"])
    return out


def choose_market_input(
    *,
    base_historical: Path,
    merged_historical: Path,
    early_snapshot: Path,
    closing_snapshot: Path,
) -> dict[str, Any]:
    if early_snapshot.exists() and closing_snapshot.exists():
        return {
            "mode": "merge_real_snapshots",
            "input": merged_historical,
            "strict": True,
            "reason": "early and closing snapshot files exist",
        }
    if _snapshot_report_ready(merged_historical):
        return {
            "mode": "use_existing_merged_snapshots",
            "input": merged_historical,
            "strict": True,
            "reason": "merged dataset has a passing market snapshot report",
        }
    return {
        "mode": "blocked_missing_real_snapshots",
        "input": base_historical,
        "strict": False,
        "reason": "real early/closing snapshot files are not both available",
    }


def refresh_current_stage4(args: argparse.Namespace) -> dict[str, Any]:
    decision_log = Path(args.decision_log)
    derived_bets = Path(args.derived_bets)
    output_dir = Path(args.output_dir)
    replay_report = Path(args.replay_report)
    latency = Path(args.latency)
    coverage_json = Path(args.coverage_json)
    market_outdir = Path(args.market_outdir)
    base_historical = Path(args.base_historical)
    merged_historical = Path(args.merged_historical)
    early_snapshot = Path(args.early_snapshot)
    closing_snapshot = Path(args.closing_snapshot)

    steps: list[dict[str, Any]] = []
    coverage_json.parent.mkdir(parents=True, exist_ok=True)

    derived_rows = derive_bets_csv(decision_log, derived_bets)
    steps.append({"name": "derive_bets_csv", "passed": True, "rows": derived_rows})

    replay = ReplayEngine(loader=HistoricalSnapshotLoader()).replay(decision_log, out_report=replay_report)
    steps.append({"name": "replay_report", "passed": True, "summary": replay.get("summary", {})})

    if not args.skip_latency:
        previous_latency = _load_json(latency)
        baseline_p99 = previous_latency.get("baseline_p99", previous_latency.get("p99"))
        latency_cmd = [
            sys.executable,
            "-m",
            "scripts.load_test",
            str(args.latency_concurrency),
            str(args.latency_requests_per_worker),
            "--mock-only",
            "--ci-output",
            str(latency),
        ]
        if baseline_p99 is not None:
            latency_cmd.extend(["--baseline-p99", str(baseline_p99)])
        steps.append(
            {
                "name": "latency",
                **_run(latency_cmd),
            }
        )

    if not args.skip_coverage:
        steps.append(
            {
                "name": "critical_path_coverage",
                **_run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "--cov=core",
                        "--cov=scripts.stage4_readiness_gate",
                        "--cov=scripts.bet_type_metrics_report",
                        "--cov-branch",
                        f"--cov-report=json:{coverage_json}",
                        "tests/test_replay_determinism.py",
                        "tests/test_replay_engine_coverage.py",
                        "tests/test_risk_clamp.py",
                        "tests/test_bet_executor_ev.py",
                        "tests/test_critical_path_coverage_gate.py",
                        "tests/test_latency_regression.py",
                        "tests/test_stage4_readiness_gate.py",
                        "tests/test_bet_types.py",
                        "tests/test_bet_type_metrics_report.py",
                    ]
                ),
            }
        )

    market_plan = choose_market_input(
        base_historical=base_historical,
        merged_historical=merged_historical,
        early_snapshot=early_snapshot,
        closing_snapshot=closing_snapshot,
    )
    if market_plan["mode"] == "merge_real_snapshots":
        steps.append(
            {
                "name": "merge_market_snapshots",
                **_run(
                    [
                        sys.executable,
                        "-m",
                        "scripts.merge_market_snapshots",
                        "--base",
                        str(base_historical),
                        "--output",
                        str(merged_historical),
                        "--join-keys",
                        args.join_keys,
                        "--early-snapshot",
                        str(early_snapshot),
                        "--closing-snapshot",
                        str(closing_snapshot),
                    ]
                ),
            }
        )

    should_refresh_market = market_plan["strict"] or args.refresh_base_market or not _market_outputs_exist(market_outdir)
    if should_refresh_market:
        market_cmd = [
            sys.executable,
            "-m",
            "scripts.market_dependency_report",
            "--input",
            str(market_plan["input"]),
            "--outdir",
            str(market_outdir),
            "--model-kind",
            args.market_model_kind,
            "--train-ratio",
            str(args.market_train_ratio),
            "--folds",
            str(args.market_folds),
        ]
        if market_plan["strict"]:
            market_cmd.append("--strict")
        steps.append({"name": "market_dependency", **_run(market_cmd)})
    else:
        steps.append(
            {
                "name": "market_dependency",
                "passed": True,
                "mode": "reuse_existing_outputs",
                "reason": "real snapshot files are absent and current market outputs already exist",
            }
        )

    if Path(market_plan["input"]).exists() and Path(market_plan["input"]) != base_historical:
        steps.append(
            {
                "name": "feature_drift_report",
                **_run(
                    [
                        sys.executable,
                        "-m",
                        "scripts.feature_drift_report",
                        "--baseline",
                        str(base_historical),
                        "--current",
                        str(market_plan["input"]),
                        "--output",
                        str(output_dir / "feature_drift_report.json"),
                    ],
                    expected_failure=True,
                ),
            }
        )

    gate_cmd = [
        sys.executable,
        "-m",
        "scripts.stage4_readiness_gate",
        "--decision-log",
        str(decision_log),
        "--latency",
        str(latency),
        "--market-outdir",
        str(market_outdir),
        "--derived-bets",
        str(derived_bets),
        "--coverage-json",
        str(coverage_json),
        "--replay-report",
        str(replay_report),
        "--require-replay-report",
        "--output",
        str(output_dir / "readiness_gate.json"),
    ]
    steps.append({"name": "readiness_gate", **_run(gate_cmd, expected_failure=True)})

    bundle_cmd = [
        sys.executable,
        "-m",
        "scripts.stage4_evidence_bundle",
        "--decision-log",
        str(decision_log),
        "--latency",
        str(latency),
        "--market-outdir",
        str(market_outdir),
        "--derived-bets",
        str(derived_bets),
        "--coverage-json",
        str(coverage_json),
        "--input-replay-report",
        str(replay_report),
        "--output-dir",
        str(output_dir),
    ]
    steps.append({"name": "evidence_bundle", **_run(bundle_cmd, expected_failure=True)})

    bundle = _load_json(output_dir / "evidence_summary.json")
    preflight = _preflight_report(
        readiness_passed=bool(bundle.get("passed")),
        status_path=Path(args.preflight_status) if args.preflight_status else None,
    )
    _write_json(output_dir / "limited_production_rehearsal_preflight.json", preflight)
    rehearsal = {
        "passed": bool(bundle.get("passed")) and preflight["passed"],
        "derived_bets_rows": derived_rows,
        "market_outputs": {
            "variant_summary": str(market_outdir / "variant_summary.csv"),
            "odds_regime_summary": str(market_outdir / "odds_regime_summary.csv"),
            "race_class_summary": str(market_outdir / "race_class_summary.csv"),
            "odds_perturbation_summary": str(market_outdir / "odds_perturbation_summary.csv"),
            "markdown": str(market_outdir / "market_dependency_report.md"),
        },
        "bundle": bundle,
        "preflight": preflight,
        "preflight_path": str(output_dir / "limited_production_rehearsal_preflight.json"),
    }
    _write_json(output_dir / "rehearsal_evidence_summary.json", rehearsal)
    steps.append({"name": "rehearsal_evidence", "passed": True, "mode": "reuse_current_market_outputs"})

    build_survivability_report(
        readiness_path=output_dir / "readiness_gate.json",
        replay_path=replay_report,
        latency_path=latency,
        preflight_path=output_dir / "limited_production_rehearsal_preflight.json",
        derived_bets_path=derived_bets,
        output_md=output_dir / "survivability_evaluation_v2.md",
        output_json=output_dir / "survivability_evaluation_v2.json",
    )
    steps.append({"name": "survivability_report", "passed": True})

    blockers = build_blockers_report(
        survivability_json=output_dir / "survivability_evaluation_v2.json",
        readiness_json=output_dir / "readiness_gate.json",
        output_md=output_dir / "evidence_blockers.md",
    )
    steps.append({"name": "evidence_blockers", "passed": True, "blockers": blockers.get("blockers", [])})

    build_rubric_report(
        readiness_path=output_dir / "readiness_gate.json",
        survivability_path=output_dir / "survivability_evaluation_v2.json",
        latency_path=latency,
        drift_path=output_dir / "feature_drift_report.json",
        output_json=output_dir / "rubric_v2_2_compliance.json",
        output_md=output_dir / "rubric_v2_2_compliance.md",
    )
    steps.append({"name": "rubric_v2_2_compliance", "passed": True})

    readiness = _load_json(output_dir / "readiness_gate.json")
    summary = {
        "passed": all(step.get("passed") for step in steps),
        "release_gate_passed": bool(readiness.get("passed")),
        "current_state": {
            "shadow_days": readiness.get("shadow_days"),
            "required_shadow_days": readiness.get("required_shadow_days"),
            "bet_submitted": readiness.get("checks", {}).get("event_chain", {}).get("bet_submitted"),
            "derived_bets_rows": derived_rows,
        },
        "market_plan": _jsonable_market_plan(market_plan),
        "blocking_reasons": readiness.get("blocking_reasons", []),
        "steps": steps,
    }
    _write_json(Path(args.summary), summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh current Stage 4 evidence without fabricating blockers")
    parser.add_argument("--decision-log", default="logs/decisions.jsonl")
    parser.add_argument("--derived-bets", default="derived/bets.csv")
    parser.add_argument("--replay-report", default="reports/stage4/replay_report.json")
    parser.add_argument("--latency", default=".ci_latency.json")
    parser.add_argument("--coverage-json", default="reports/stage4/critical_path_coverage.json")
    parser.add_argument("--market-outdir", default="results/market_dependency")
    parser.add_argument("--output-dir", default="reports/stage4")
    parser.add_argument("--base-historical", default="data/processed/historical_dataset.csv")
    parser.add_argument("--merged-historical", default="data/processed/historical_dataset_with_market_snapshots.csv")
    parser.add_argument("--early-snapshot", default="data/market_snapshots/early_odds.csv")
    parser.add_argument("--closing-snapshot", default="data/market_snapshots/closing_odds.csv")
    parser.add_argument("--join-keys", default="race_id,horse_id")
    parser.add_argument("--preflight-status", default="reports/stage4/preflight_status.json")
    parser.add_argument("--summary", default="reports/stage4/current_update_summary.json")
    parser.add_argument("--latency-concurrency", type=int, default=2)
    parser.add_argument("--latency-requests-per-worker", type=int, default=10)
    parser.add_argument("--market-model-kind", choices=("boosted", "logistic"), default="logistic")
    parser.add_argument("--market-train-ratio", type=float, default=0.7)
    parser.add_argument("--market-folds", type=int, default=2)
    parser.add_argument(
        "--refresh-base-market",
        action="store_true",
        help="Regenerate market dependency from the base historical dataset even when real snapshots are absent.",
    )
    parser.add_argument("--skip-latency", action="store_true")
    parser.add_argument("--skip-coverage", action="store_true")
    return parser.parse_args()


def main() -> int:
    report = refresh_current_stage4(parse_args())
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
