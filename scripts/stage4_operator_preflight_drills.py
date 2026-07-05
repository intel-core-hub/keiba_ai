from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SHADOW_MODE", "1")
os.environ.setdefault("SAFE_MODE", "1")

from core.betting.decision_engine import Decision
from core.betting.risk_clamp import RiskClamp, RiskClampInput
from core.execution.bet_executor import BetExecutor
from scripts.derive_bets_csv_from_decisions import AUDIT_TRACE_FIELDS, derive


DRILLS = {
    "operator_kill_switch_tested": "kill_switch",
    "manual_override_tested": "manual_override",
    "max_exposure_cap_enforced": "max_exposure_cap",
    "bankroll_reconciliation_tested": "bankroll_reconciliation",
    "tax_audit_export_reproduced": "tax_audit_export",
}


@dataclass
class DrillResult:
    key: str
    name: str
    passed: bool
    command: str
    expected: str
    actual: str
    artifact_path: Path
    payload: dict[str, Any]


class _StubRisk:
    bankroll = 100_000.0

    def status(self) -> dict[str, Any]:
        return {
            "bankroll": self.bankroll,
            "drawdown": 0.0,
            "risk_multiplier": 1.0,
            "lose_streak": 0,
            "win_streak": 0,
            "race_risk_used": 0.0,
        }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _decision() -> Decision:
    decision = Decision(
        race_id="PREFLIGHT_R1",
        selection="H1",
        probability=0.2,
        calibrated_probability=0.18,
        market_probability=0.1,
        odds=10.0,
        edge=0.05,
        expected_value=0.8,
        uncertainty_score=0.1,
        edge_quality=0.7,
        bet_size=500,
    )
    decision.risk_limits_hash = "preflight-risk-hash"
    decision.risk_clamp_reason = "risk_clamp_allowed"
    decision.risk_clamp_allowed = True
    decision.policy_hash = "preflight-policy-hash"
    decision.model_hash = "preflight-model-hash"
    decision.odds_snapshot_hash = "preflight-odds-hash"
    decision.feature_snapshot_hash = "preflight-feature-hash"
    return decision


def _executor(work_dir: Path) -> BetExecutor:
    return BetExecutor(
        risk_manager=_StubRisk(),
        decision_log_path=str(work_dir / "preflight_decisions.jsonl"),
        csv_report_path=str(work_dir / "preflight_bets.csv"),
        shadow_mode=True,
        safe_mode=True,
    )


def _kill_switch(artifacts: Path) -> DrillResult:
    artifact = artifacts / "kill_switch.json"
    executor = _executor(artifacts)
    shutdown = executor.emergency_shutdown("operator_preflight_kill_switch", source="stage4_preflight")
    result = executor.execute_bet(_decision())
    passed = bool(shutdown.get("blocked")) and bool(result.get("blocked")) and result.get("state") == "STANDBY"
    payload = {"shutdown": shutdown, "execute_result": result, "passed": passed}
    _write_json(artifact, payload)
    return DrillResult(
        key="operator_kill_switch_tested",
        name="kill_switch",
        passed=passed,
        command="python -m scripts.stage4_operator_preflight_drills --only kill_switch",
        expected="Emergency kill switch places executor in STANDBY and blocks a shadow bet.",
        actual=f"blocked={result.get('blocked')} state={result.get('state')} reason={result.get('reason')}",
        artifact_path=artifact,
        payload=payload,
    )


def _manual_override(artifacts: Path) -> DrillResult:
    artifact = artifacts / "manual_override.json"
    executor = _executor(artifacts)
    executor.emergency_shutdown("operator_preflight_manual_override", source="stage4_preflight")
    blocked_before = executor.is_blocked()
    executor.resume_from_emergency()
    blocked_after = executor.is_blocked()
    passed = blocked_before is True and blocked_after is False
    payload = {"blocked_before": blocked_before, "blocked_after": blocked_after, "passed": passed}
    _write_json(artifact, payload)
    return DrillResult(
        key="manual_override_tested",
        name="manual_override",
        passed=passed,
        command="python -m scripts.stage4_operator_preflight_drills --only manual_override",
        expected="Manual override/resume clears emergency STANDBY without live execution.",
        actual=f"blocked_before={blocked_before} blocked_after={blocked_after}",
        artifact_path=artifact,
        payload=payload,
    )


def _max_exposure_cap(artifacts: Path) -> DrillResult:
    artifact = artifacts / "max_exposure_cap.json"
    clamp = RiskClamp()
    result = clamp.evaluate(
        RiskClampInput(
            odds_snapshot={"present": True},
            feature_snapshot={"present": True},
            calibration_state={"expired": False, "invalid": False},
            bankroll_snapshot={"bankroll": 100_000.0, "drawdown": 0.0},
            race_state={"race_cancelled": False},
            clock_state={"clock_skew_ms": 0},
            model_state={"expected_hash": "model-a", "active_hash": "model-a"},
            policy_snapshot={
                "expected_hash": "policy-a",
                "active_hash": "policy-a",
                "max_odds_age_ms": 2_000,
                "max_feature_age_ms": 5_000,
                "max_clock_skew_ms": 500,
                "max_exposure_pct": 0.0,
            },
            sizing_proposal={
                "allowed": False,
                "amount": 1_000_000.0,
                "max_stake": 0.0,
                "risk_multiplier": 0.0,
                "reason": "risk_limits_invalid",
            },
            odds_freshness_ms=100.0,
            feature_age_ms=100.0,
        )
    )
    passed = result.allowed is False and result.decision == "NO_BET" and result.reason == "risk_limits_invalid"
    payload = {"result": result.__dict__, "passed": passed}
    _write_json(artifact, payload)
    return DrillResult(
        key="max_exposure_cap_enforced",
        name="max_exposure_cap",
        passed=passed,
        command="python -m scripts.stage4_operator_preflight_drills --only max_exposure_cap",
        expected="RiskClamp rejects an excessive sizing proposal with NO_BET.",
        actual=f"decision={result.decision} reason={result.reason} allowed={result.allowed}",
        artifact_path=artifact,
        payload=payload,
    )


def _csv_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _bankroll_reconciliation(artifacts: Path, *, decision_log: Path, derived_bets: Path) -> DrillResult:
    artifact = artifacts / "bankroll_reconciliation.json"
    reproduced = artifacts / "bankroll_reconciliation_bets.csv"
    row_count = derive(decision_log, reproduced)
    current_rows = _csv_count(derived_bets) if derived_bets.exists() else None
    passed = row_count > 0 and current_rows == row_count
    payload = {
        "decision_log": str(decision_log),
        "derived_bets": str(derived_bets),
        "reproduced_csv": str(reproduced),
        "canonical_rows": row_count,
        "current_rows": current_rows,
        "passed": passed,
    }
    _write_json(artifact, payload)
    return DrillResult(
        key="bankroll_reconciliation_tested",
        name="bankroll_reconciliation",
        passed=passed,
        command="python -m scripts.stage4_operator_preflight_drills --only bankroll_reconciliation",
        expected="Canonical JSONL-derived report row count matches current derived/bets.csv.",
        actual=f"canonical_rows={row_count} current_rows={current_rows}",
        artifact_path=artifact,
        payload=payload,
    )


def _tax_audit_export(artifacts: Path, *, decision_log: Path) -> DrillResult:
    artifact = artifacts / "tax_audit_export.json"
    export_csv = artifacts / "tax_audit_export_bets.csv"
    row_count = derive(decision_log, export_csv)
    with export_csv.open(newline="", encoding="utf-8") as handle:
        header = list(csv.DictReader(handle).fieldnames or [])
    missing = [field for field in AUDIT_TRACE_FIELDS if field not in header]
    passed = row_count > 0 and not missing
    payload = {
        "decision_log": str(decision_log),
        "export_csv": str(export_csv),
        "row_count": row_count,
        "missing_audit_trace_fields": missing,
        "passed": passed,
    }
    _write_json(artifact, payload)
    return DrillResult(
        key="tax_audit_export_reproduced",
        name="tax_audit_export",
        passed=passed,
        command="python -m scripts.stage4_operator_preflight_drills --only tax_audit_export",
        expected="Tax/audit export is reproducible from canonical decisions JSONL with audit trace fields.",
        actual=f"row_count={row_count} missing_audit_trace_fields={missing}",
        artifact_path=artifact,
        payload=payload,
    )


def _markdown(result: DrillResult, *, operator: str, timestamp: str) -> str:
    status = "PASS" if result.passed else "FAIL"
    return "\n".join(
        [
            f"# Drill: {result.name}",
            "",
            "## Timestamp",
            timestamp,
            "",
            "## Operator",
            operator,
            "",
            "## Command / Action",
            result.command,
            "",
            "## Expected Result",
            result.expected,
            "",
            "## Actual Result",
            result.actual,
            "",
            "## Evidence",
            f"- artifact path: {result.artifact_path}",
            "",
            "## Result",
            status,
            "",
        ]
    )


def _write_status(path: Path, results: list[DrillResult]) -> None:
    existing = _read_json(path)
    evidence_paths = existing.get("evidence_paths", {})
    if not isinstance(evidence_paths, dict):
        evidence_paths = {}
    for result in results:
        existing[result.key] = bool(result.passed)
        evidence_paths[result.name] = f"reports/stage4/preflight_drills/{result.name}.md"
    existing["evidence_paths"] = evidence_paths
    _write_json(path, existing)


def run_drills(
    *,
    output_dir: Path,
    status_path: Path,
    decision_log: Path,
    derived_bets: Path,
    operator: str,
    only: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = output_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    drill_fns: dict[str, Callable[[], DrillResult]] = {
        "kill_switch": lambda: _kill_switch(artifacts),
        "manual_override": lambda: _manual_override(artifacts),
        "max_exposure_cap": lambda: _max_exposure_cap(artifacts),
        "bankroll_reconciliation": lambda: _bankroll_reconciliation(
            artifacts,
            decision_log=decision_log,
            derived_bets=derived_bets,
        ),
        "tax_audit_export": lambda: _tax_audit_export(artifacts, decision_log=decision_log),
    }
    selected = [only] if only else list(drill_fns)
    unknown = [name for name in selected if name not in drill_fns]
    if unknown:
        raise ValueError(f"unknown drill(s): {unknown}")

    results = [drill_fns[name]() for name in selected]
    for result in results:
        (output_dir / f"{result.name}.md").write_text(
            _markdown(result, operator=operator, timestamp=timestamp),
            encoding="utf-8",
        )
    _write_status(status_path, results)
    summary = {
        "passed": all(result.passed for result in results),
        "results": {
            result.name: {
                "passed": result.passed,
                "artifact_path": str(result.artifact_path),
                "actual": result.actual,
            }
            for result in results
        },
        "status_path": str(status_path),
        "output_dir": str(output_dir),
    }
    _write_json(artifacts / "preflight_drill_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Stage 4 operator preflight drills in SHADOW/SAFE mode")
    parser.add_argument("--output-dir", default="reports/stage4/preflight_drills")
    parser.add_argument("--status", default="reports/stage4/preflight_status.json")
    parser.add_argument("--decision-log", default="logs/decisions.jsonl")
    parser.add_argument("--derived-bets", default="derived/bets.csv")
    parser.add_argument("--operator", default=os.getenv("USERNAME") or os.getenv("USER") or "operator")
    parser.add_argument("--only", choices=list(DRILLS.values()), default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_drills(
        output_dir=Path(args.output_dir),
        status_path=Path(args.status),
        decision_log=Path(args.decision_log),
        derived_bets=Path(args.derived_bets),
        operator=args.operator,
        only=args.only,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
