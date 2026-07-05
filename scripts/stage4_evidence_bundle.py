from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.replay.historical_snapshot_loader import HistoricalSnapshotLoader
from core.replay.replay_engine import ReplayEngine
from scripts.stage4_readiness_gate import evaluate_gate


REQUIRED_MARKET_FILES = (
    "variant_summary.csv",
    "odds_regime_summary.csv",
    "race_class_summary.csv",
    "odds_perturbation_summary.csv",
)


def _json_safe_path(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _required_artifact_status(
    *,
    decision_log: Path,
    latency: Path,
    market_outdir: Path,
    derived_bets: Path,
    coverage_json: Path,
    bet_type_metrics: Path,
    rubric_v2_3_report: Path,
    degradation_report: Path,
) -> dict[str, Any]:
    required = {
        "decision_log": decision_log,
        "latency": latency,
        "derived_bets": derived_bets,
        "coverage_json": coverage_json,
    }
    required_evidence = {
        "bet_type_metrics": bet_type_metrics,
        "rubric_v2_3_report": rubric_v2_3_report,
        "degradation_report": degradation_report,
    }
    missing = [name for name, path in required.items() if not path.exists()]
    missing_evidence = [name for name, path in required_evidence.items() if not path.exists()]
    missing_market = [name for name in REQUIRED_MARKET_FILES if not (market_outdir / name).exists()]
    if missing_market:
        missing.append("market_dependency")
    missing.extend(missing_evidence)
    return {
        "passed": not missing,
        "missing": missing,
        "missing_evidence": missing_evidence,
        "missing_market_files": missing_market,
    }


def _prepare_replay_report(
    *,
    decision_log: Path,
    output_replay_report: Path,
    input_replay_report: Path | None,
    odds_snapshots: Path | None,
    feature_snapshots: Path | None,
    calibration_snapshots: Path | None,
    timestamp_col: str,
) -> dict[str, Any]:
    output_replay_report.parent.mkdir(parents=True, exist_ok=True)
    if input_replay_report is not None:
        if not input_replay_report.exists():
            return {"passed": False, "reason": "input_replay_report_missing", "path": str(input_replay_report)}
        if input_replay_report.resolve() != output_replay_report.resolve():
            shutil.copyfile(input_replay_report, output_replay_report)
        return {"passed": True, "source": "provided_report", "path": str(output_replay_report)}

    snapshot_paths = [odds_snapshots, feature_snapshots, calibration_snapshots]
    if not all(path is not None and path.exists() for path in snapshot_paths):
        return {
            "passed": False,
            "reason": "missing_replay_evidence",
            "required": ["input_replay_report", "odds_snapshots", "feature_snapshots", "calibration_snapshots"],
        }

    replay = ReplayEngine(
        loader=HistoricalSnapshotLoader(
            odds_csv=odds_snapshots,
            features_csv=feature_snapshots,
            calibration_csv=calibration_snapshots,
            timestamp_col=timestamp_col,
        )
    )
    replay.replay(decision_log, out_report=output_replay_report)
    return {"passed": True, "source": "generated_from_snapshots", "path": str(output_replay_report)}


def build_evidence_bundle(
    *,
    decision_log: Path,
    latency: Path,
    market_outdir: Path,
    derived_bets: Path,
    output_dir: Path,
    coverage_json: Path = Path("reports/stage4/critical_path_coverage.json"),
    input_replay_report: Path | None = None,
    odds_snapshots: Path | None = None,
    feature_snapshots: Path | None = None,
    calibration_snapshots: Path | None = None,
    timestamp_col: str = "timestamp",
    bet_type_metrics: Path = Path("reports/stage4/bet_type_metrics.json"),
    rubric_v2_3_report: Path = Path("reports/stage4/rubric_v2_3_compliance.json"),
    degradation_report: Path = Path("reports/stage4/degradation_mode_report.json"),
    optional: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    replay_report = output_dir / "replay_report.json"
    summary_path = output_dir / "evidence_summary.json"
    readiness_path = output_dir / "readiness_gate.json"

    artifact_status = _required_artifact_status(
        decision_log=decision_log,
        latency=latency,
        market_outdir=market_outdir,
        derived_bets=derived_bets,
        coverage_json=coverage_json,
        bet_type_metrics=bet_type_metrics,
        rubric_v2_3_report=rubric_v2_3_report,
        degradation_report=degradation_report,
    )
    report: dict[str, Any] = {
        "passed": False,
        "optional": optional,
        "skipped": False,
        "artifacts": {
            "decision_log": str(decision_log),
            "latency": str(latency),
            "market_outdir": str(market_outdir),
            "derived_bets": str(derived_bets),
            "coverage_json": str(coverage_json),
            "replay_report": str(replay_report),
            "input_replay_report": _json_safe_path(input_replay_report),
            "odds_snapshots": _json_safe_path(odds_snapshots),
            "feature_snapshots": _json_safe_path(feature_snapshots),
            "calibration_snapshots": _json_safe_path(calibration_snapshots),
            "bet_type_metrics_path": str(bet_type_metrics),
            "rubric_v2_3_report_path": str(rubric_v2_3_report),
            "degradation_mode_report_path": str(degradation_report),
        },
        "artifact_status": artifact_status,
        "bet_type_metrics_path": str(bet_type_metrics),
        "rubric_v2_3_report_path": str(rubric_v2_3_report),
        "degradation_mode_report_path": str(degradation_report),
    }
    if bet_type_metrics.exists():
        metrics_payload = _load_json(bet_type_metrics)
        for key in (
            "production_candidate_bet_types",
            "shadow_only_bet_types",
            "disabled_bet_types",
            "shadow_only_violation_count",
            "disabled_bet_type_candidate_count",
            "production_execution_unknown_bet_type_count",
            "bet_type_missing_count",
            "old_win_compat_conversion_count",
        ):
            report[key] = metrics_payload.get(key)
    if rubric_v2_3_report.exists():
        rubric_payload = _load_json(rubric_v2_3_report)
        report["rubric_v2_3_final_rank"] = rubric_payload.get("final_stage4_rank")
        report["rubric_v2_3_release_recommendation"] = rubric_payload.get("release_recommendation")
    if degradation_report.exists():
        degradation_payload = _load_json(degradation_report)
        report["degradation_critical_count"] = degradation_payload.get("degradation_critical_count")
        report["degradation_force_no_bet_count"] = degradation_payload.get("degradation_force_no_bet_count")
        report["degradation_restrict_count"] = degradation_payload.get("degradation_restrict_count")
        report["degradation_recommendation"] = degradation_payload.get("recommendation")

    if not artifact_status["passed"]:
        report["skipped"] = optional
        report["reason"] = "missing_required_artifacts"
        _write_json(readiness_path, {"passed": False, "failures": ["required_artifacts"], "checks": {"artifact_status": artifact_status}})
        _write_json(summary_path, report)
        return report

    replay_status = _prepare_replay_report(
        decision_log=decision_log,
        output_replay_report=replay_report,
        input_replay_report=input_replay_report,
        odds_snapshots=odds_snapshots,
        feature_snapshots=feature_snapshots,
        calibration_snapshots=calibration_snapshots,
        timestamp_col=timestamp_col,
    )
    report["replay_status"] = replay_status
    if not replay_status["passed"]:
        report["skipped"] = optional
        report["reason"] = replay_status["reason"]
        _write_json(readiness_path, {"passed": False, "failures": ["replay"], "checks": {"replay_status": replay_status}})
        _write_json(summary_path, report)
        return report

    gate = evaluate_gate(
        decision_log=decision_log,
        latency=latency,
        market_outdir=market_outdir,
        derived_bets=derived_bets,
        coverage_json=coverage_json,
        replay_report=replay_report,
        require_replay_report=True,
    ).to_dict()
    report["gate"] = gate
    report["passed"] = bool(gate.get("passed"))
    _write_json(readiness_path, gate)
    _write_json(summary_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build mandatory Stage 4 candidate evidence bundle")
    parser.add_argument("--decision-log", default="logs/decisions.jsonl")
    parser.add_argument("--latency", default=".ci_latency.json")
    parser.add_argument("--market-outdir", default="results/market_dependency")
    parser.add_argument("--derived-bets", default="derived/bets.csv")
    parser.add_argument("--coverage-json", default="reports/stage4/critical_path_coverage.json")
    parser.add_argument("--output-dir", default="reports/stage4")
    parser.add_argument("--input-replay-report", default=None)
    parser.add_argument("--odds-snapshots", default=None)
    parser.add_argument("--feature-snapshots", default=None)
    parser.add_argument("--calibration-snapshots", default=None)
    parser.add_argument("--timestamp-col", default="timestamp")
    parser.add_argument("--bet-type-metrics", default="reports/stage4/bet_type_metrics.json")
    parser.add_argument("--rubric-v2-3-report", default="reports/stage4/rubric_v2_3_compliance.json")
    parser.add_argument("--degradation-report", default="reports/stage4/degradation_mode_report.json")
    parser.add_argument(
        "--optional",
        action="store_true",
        help="Return success when evidence is absent, but write a non-passing summary without claiming Stage 4.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_evidence_bundle(
        decision_log=Path(args.decision_log),
        latency=Path(args.latency),
        market_outdir=Path(args.market_outdir),
        derived_bets=Path(args.derived_bets),
        coverage_json=Path(args.coverage_json),
        output_dir=Path(args.output_dir),
        input_replay_report=Path(args.input_replay_report) if args.input_replay_report else None,
        odds_snapshots=Path(args.odds_snapshots) if args.odds_snapshots else None,
        feature_snapshots=Path(args.feature_snapshots) if args.feature_snapshots else None,
        calibration_snapshots=Path(args.calibration_snapshots) if args.calibration_snapshots else None,
        timestamp_col=args.timestamp_col,
        bet_type_metrics=Path(args.bet_type_metrics),
        rubric_v2_3_report=Path(args.rubric_v2_3_report),
        degradation_report=Path(args.degradation_report),
        optional=args.optional,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] or args.optional else 1


if __name__ == "__main__":
    raise SystemExit(main())
