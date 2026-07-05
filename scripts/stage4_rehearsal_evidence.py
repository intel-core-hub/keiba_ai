from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.derive_bets_csv_from_decisions import derive as derive_bets_csv
from scripts.market_dependency_report import generate_report as generate_market_dependency_report
from scripts.stage4_evidence_bundle import build_evidence_bundle


PREFLIGHT_CHECKS = {
    "stage4_release_gate_passed": "Stage 4 Release Gate passed",
    "operator_kill_switch_tested": "operator kill switch tested",
    "manual_override_tested": "manual override tested",
    "max_exposure_cap_enforced": "max exposure cap enforced",
    "bankroll_reconciliation_tested": "bankroll reconciliation tested",
    "tax_audit_export_reproduced": "tax/audit export reproduced",
}

PREFLIGHT_EVIDENCE_ALIASES = {
    "operator_kill_switch_tested": "kill_switch",
    "manual_override_tested": "manual_override",
    "max_exposure_cap_enforced": "max_exposure_cap",
    "bankroll_reconciliation_tested": "bankroll_reconciliation",
    "tax_audit_export_reproduced": "tax_audit_export",
}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_preflight_status(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"checks": {}, "evidence_paths": {}}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("preflight status must be a JSON object")
    missing = [key for key in PREFLIGHT_CHECKS if key != "stage4_release_gate_passed" and key not in payload]
    if missing:
        raise ValueError(f"preflight status missing required fields: {missing}")
    evidence_paths = payload.get("evidence_paths", {})
    if evidence_paths is None:
        evidence_paths = {}
    if not isinstance(evidence_paths, dict):
        raise ValueError("preflight evidence_paths must be a JSON object")
    return {
        "checks": {key: bool(payload.get(key)) for key in PREFLIGHT_CHECKS},
        "evidence_paths": evidence_paths,
    }


def _preflight_evidence_path(status_path: Path | None, status: dict[str, Any], key: str) -> Path | None:
    if status_path is None:
        return None
    evidence_paths = status.get("evidence_paths", {})
    alias = PREFLIGHT_EVIDENCE_ALIASES.get(key, key)
    configured = evidence_paths.get(alias) or evidence_paths.get(key)
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = status_path.parent.parent.parent / candidate
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    evidence_dir = status_path.parent / "preflight_drills"
    for stem in (alias, key):
        for suffix in (".json", ".md", ".txt"):
            candidate = evidence_dir / f"{stem}{suffix}"
            if candidate.exists() and candidate.stat().st_size > 0:
                return candidate
    return None


def _preflight_evidence_passed(path: Path | None) -> bool:
    if path is None:
        return False
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        result = str(payload.get("result", "")).strip().upper()
        return payload.get("passed") is True or result == "PASS"
    text = path.read_text(encoding="utf-8", errors="ignore")
    return re.search(r"(?im)^##\s*Result\s*\n\s*PASS\s*$|^Result\s*:\s*PASS\s*$", text) is not None


def _preflight_report(*, readiness_passed: bool, status_path: Path | None) -> dict[str, Any]:
    status = _load_preflight_status(status_path)
    status_checks = status["checks"]
    checks = {}
    for key, label in PREFLIGHT_CHECKS.items():
        value = readiness_passed if key == "stage4_release_gate_passed" else bool(status_checks.get(key, False))
        evidence_path = None
        if key != "stage4_release_gate_passed" and value:
            evidence_path = _preflight_evidence_path(status_path, status, key)
            value = _preflight_evidence_passed(evidence_path)
        checks[key] = {
            "passed": value,
            "label": label,
            "evidence_path": str(evidence_path) if evidence_path is not None else None,
        }
    missing = [key for key, value in checks.items() if not value["passed"]]
    return {"passed": not missing, "missing": missing, "checks": checks}


def run_rehearsal_evidence(
    *,
    decision_log: Path,
    historical_data: Path,
    latency: Path,
    market_outdir: Path,
    derived_bets: Path,
    coverage_json: Path,
    output_dir: Path,
    input_replay_report: Path | None,
    odds_snapshots: Path | None,
    feature_snapshots: Path | None,
    calibration_snapshots: Path | None,
    timestamp_col: str,
    model_kind: str,
    train_ratio: float,
    folds: int,
    preflight_status: Path | None = None,
) -> dict[str, Any]:
    derived_count = derive_bets_csv(decision_log, derived_bets)
    market_paths = generate_market_dependency_report(
        input_path=historical_data,
        outdir=market_outdir,
        model_kind=model_kind,
        train_ratio=train_ratio,
        folds=folds,
    )
    bundle = build_evidence_bundle(
        decision_log=decision_log,
        latency=latency,
        market_outdir=market_outdir,
        derived_bets=derived_bets,
        coverage_json=coverage_json,
        output_dir=output_dir,
        input_replay_report=input_replay_report,
        odds_snapshots=odds_snapshots,
        feature_snapshots=feature_snapshots,
        calibration_snapshots=calibration_snapshots,
        timestamp_col=timestamp_col,
        optional=False,
    )
    preflight = _preflight_report(readiness_passed=bool(bundle.get("passed")), status_path=preflight_status)
    preflight_path = output_dir / "limited_production_rehearsal_preflight.json"
    _write_json(preflight_path, preflight)

    report = {
        "passed": bool(bundle.get("passed")) and preflight["passed"],
        "derived_bets_rows": derived_count,
        "market_outputs": {key: str(value) for key, value in market_paths.items()},
        "bundle": bundle,
        "preflight": preflight,
        "preflight_path": str(preflight_path),
    }
    _write_json(output_dir / "rehearsal_evidence_summary.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Stage 4.1 limited-production rehearsal evidence")
    parser.add_argument("--decision-log", default="logs/decisions.jsonl")
    parser.add_argument("--historical-data", default="data/processed/historical_dataset.csv")
    parser.add_argument("--latency", default=".ci_latency.json")
    parser.add_argument("--market-outdir", default="results/market_dependency")
    parser.add_argument("--derived-bets", default="derived/bets.csv")
    parser.add_argument("--coverage-json", default="reports/stage4/critical_path_coverage.json")
    parser.add_argument("--output-dir", default="reports/stage4")
    parser.add_argument("--input-replay-report", default="reports/stage4/replay_report.json")
    parser.add_argument("--odds-snapshots", default=None)
    parser.add_argument("--feature-snapshots", default=None)
    parser.add_argument("--calibration-snapshots", default=None)
    parser.add_argument("--timestamp-col", default="timestamp")
    parser.add_argument("--model-kind", choices=("boosted", "logistic"), default="boosted")
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--preflight-status", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_rehearsal_evidence(
        decision_log=Path(args.decision_log),
        historical_data=Path(args.historical_data),
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
        model_kind=args.model_kind,
        train_ratio=args.train_ratio,
        folds=args.folds,
        preflight_status=Path(args.preflight_status) if args.preflight_status else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
