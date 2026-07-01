from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.replay.historical_snapshot_loader import HistoricalSnapshotLoader
from core.replay.replay_engine import ReplayEngine
from core.replay.replay_validator import ReplayValidator
from schemas.audit_event import AuditEvent
from schemas.decision_event import REQUIRED_HASH_FIELDS


LATENCY_THRESHOLDS = {
    "p50": 40.0,
    "p95": 80.0,
    "p99": 200.0,
    "p999": 250.0,
    "timeout_rate": 0.0,
    "latency_regression_rate": 0.30,
}
REQUIRED_SHADOW_DAYS = 30
REQUIRED_MARKET_VARIANTS = {"full", "no_odds", "market_only", "early_odds_only", "closing_odds"}
REQUIRED_ODDS_BUCKETS = {"FAVORITE_HEAVY", "LONGSHOT", "DEEP_LONGSHOT"}
CRITICAL_PATH_BRANCH_COVERAGE_MIN = 80.0
CRITICAL_PATH_COVERAGE_FILES = (
    "core/betting/decision_engine.py",
    "core/betting/risk_clamp.py",
    "core/betting/bet_types.py",
    "core/execution/bet_executor.py",
    "core/replay/replay_engine.py",
    "scripts/stage4_readiness_gate.py",
    "scripts/bet_type_metrics_report.py",
)
CHAIN_EVENT_TYPES = {
    "OddsSnapshotReceived",
    "FeatureSnapshotBuilt",
    "PredictionMade",
    "RiskClampEvaluated",
    "BetSubmitted",
    "BetAccepted",
    "BetRejected",
    "RaceSettled",
    "BankrollUpdated",
}

EVIDENCE_FAILURE_KEYS = {
    "required_artifacts",
    "shadow_coverage",
    "market_dependency",
    "payload_hashes",
}
METRIC_FAILURE_KEYS = {
    "shadow_safety",
    "audit_envelopes",
    "event_chain",
    "latency",
    "governance_lint",
}


@dataclass
class GateResult:
    passed: bool = True
    checks: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def fail(self, key: str, details: Any) -> None:
        self.passed = False
        self.checks[key] = details
        self.failures.append(key)

    def pass_check(self, key: str, details: Any) -> None:
        self.checks[key] = details

    def to_dict(self) -> dict[str, Any]:
        evidence_failures, metric_failures = classify_failures(self.checks, self.failures)
        evidence_gate = {"passed": not evidence_failures, "failures": evidence_failures}
        metric_gate = {"passed": not metric_failures, "failures": metric_failures}
        report = {
            "passed": evidence_gate["passed"] and metric_gate["passed"],
            "failures": self.failures,
            "evidence_gate": evidence_gate,
            "metric_gate": metric_gate,
            "checks": self.checks,
            "stage4_verdict": stage4_verdict(evidence_gate, metric_gate),
            **blocking_summary(self.checks, self.failures),
        }
        report["expected_fail_only_shadow_days"] = expected_fail_only_shadow_days(report)
        return report


def classify_failures(checks: dict[str, Any], failures: list[str]) -> tuple[list[str], list[str]]:
    evidence: list[str] = []
    metric: list[str] = []
    for key in failures:
        details = checks.get(key, {})
        layer = failure_layer(key, details)
        if layer == "evidence":
            evidence.append(key)
        elif layer == "metric":
            metric.append(key)
        else:
            evidence.append(key)
    return evidence, metric


def failure_layer(key: str, details: Any) -> str:
    if key in EVIDENCE_FAILURE_KEYS:
        return "evidence"
    if key in METRIC_FAILURE_KEYS:
        return "metric"
    if key == "replay":
        reason = str(details.get("reason", "")) if isinstance(details, dict) else ""
        if "required" in reason or "missing_replay_evidence" in reason:
            return "evidence"
        return "metric"
    if key == "critical_path_coverage":
        if isinstance(details, dict) and not details.get("evidence_present", True):
            return "evidence"
        return "metric"
    return "evidence"


def stage4_verdict(evidence_gate: dict[str, Any], metric_gate: dict[str, Any]) -> str:
    if evidence_gate.get("passed") and metric_gate.get("passed"):
        return "PASS"
    if not evidence_gate.get("passed") and metric_gate.get("passed"):
        return "EVIDENCE_BLOCKED"
    if evidence_gate.get("passed") and not metric_gate.get("passed"):
        return "METRIC_FAILED"
    return "EVIDENCE_BLOCKED_AND_METRIC_FAILED"


def blocking_summary(checks: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    reasons: list[str] = []
    shadow = checks.get("shadow_coverage", {})
    shadow_days = int(shadow.get("calendar_days", 0) or 0) if isinstance(shadow, dict) else 0
    if "shadow_coverage" in failures:
        reasons.append("shadow_coverage.calendar_days < 30")

    for key in failures:
        if key == "shadow_coverage":
            continue
        details = checks.get(key, {})
        if key == "market_dependency" and isinstance(details, dict):
            for variant in details.get("missing_variants", []):
                reasons.append(f"market_dependency.{variant} missing")
            for variant in details.get("unavailable_variants", []):
                reasons.append(f"market_dependency.{variant} unavailable")
            for bucket in details.get("missing_odds_buckets", []):
                reasons.append(f"market_dependency.{bucket} bucket missing")
            for bucket in details.get("invalid_odds_buckets", []):
                reasons.append(f"market_dependency.{bucket.get('odds_regime')} bucket invalid")
            for item in details.get("missing_files", []):
                reasons.append(f"market_dependency missing {Path(item).name}")
            for scenario in details.get("missing_perturbations", []):
                reasons.append(f"market_dependency.{scenario} perturbation missing")
            if details.get("market_copy_score") is None:
                reasons.append("market_dependency.market_copy_score non_numeric")
        elif key == "replay" and isinstance(details, dict):
            for counter in (
                "replay_mismatch_count",
                "missing_hash",
                "snapshot_after_decision",
                "riskclamp_bypass",
                "stale_data_bet",
                "missing_audit_hash",
                "event_chain_mismatch",
            ):
                if int(details.get(counter, 0) or 0) > 0:
                    reasons.append(f"replay.{counter} > 0")
            if details.get("reason"):
                reasons.append(f"replay.{details['reason']}")
        elif key == "latency" and isinstance(details, dict):
            for item in details.get("failures", []):
                reasons.append(f"latency.{item}")
        elif key == "payload_hashes" and isinstance(details, dict):
            if int(details.get("missing_payload_hash", 0) or 0) > 0:
                reasons.append("audit_hash_fields.missing_payload_hash > 0")
        elif key == "critical_path_coverage" and isinstance(details, dict):
            if not details.get("evidence_present", True):
                reasons.append("critical_path_coverage.coverage_json missing")
            for item in details.get("missing_critical_files", []):
                reasons.append(f"critical_path_coverage.{item} missing")
            branch_pct = details.get("branch_coverage_pct")
            if branch_pct is not None and float(branch_pct) < CRITICAL_PATH_BRANCH_COVERAGE_MIN:
                reasons.append("critical_path_coverage.branch_coverage < 80")
        elif key == "governance_lint" and isinstance(details, dict):
            if details.get("runtime_import_violations"):
                reasons.append("governance_lint.runtime_import_violations > 0")
            if details.get("critical_path_violations"):
                reasons.append("governance_lint.critical_path_violations > 0")
            if details.get("duplicate_implementations"):
                reasons.append("governance_lint.duplicate_implementations > 0")
        elif key == "required_artifacts" and isinstance(details, dict):
            for item in details.get("missing", []):
                reasons.append(f"required_artifacts.{item} missing")
        else:
            reasons.append(key)

    if not reasons and failures:
        reasons = list(failures)
    non_shadow = [reason for reason in reasons if not reason.startswith("shadow_coverage.")]
    return {
        "blocking_reasons": reasons,
        "non_shadow_blockers": non_shadow,
        "shadow_days": shadow_days,
        "required_shadow_days": REQUIRED_SHADOW_DAYS,
    }


def expected_fail_only_shadow_days(report: dict[str, Any]) -> bool:
    reasons = list(report.get("blocking_reasons", []))
    return (
        report.get("passed") is False
        and reasons == ["shadow_coverage.calendar_days < 30"]
        and not report.get("non_shadow_blockers", [])
    )


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                events.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return events


def parse_utc(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def event_timestamp(event: dict[str, Any]) -> datetime | None:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    for key in ("occurred_at_utc", "timestamp", "decision_time_utc"):
        ts = parse_utc(event.get(key))
        if ts is not None:
            return ts
    for key in ("occurred_at_utc", "timestamp", "decision_time_utc"):
        ts = parse_utc(payload.get(key))
        if ts is not None:
            return ts
    return None


def event_type(event: dict[str, Any]) -> str | None:
    return event.get("event_type") or event.get("event")


def event_payload(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("payload") if isinstance(event.get("payload"), dict) else event


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "ok", "pass"}


def numeric(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def validate_shadow_coverage(events: list[dict[str, Any]]) -> dict[str, Any]:
    dates = sorted({ts.date() for event in events if (ts := event_timestamp(event)) is not None})
    if not dates:
        return {"passed": False, "calendar_days": 0, "reason": "no_event_timestamps"}
    return {
        "passed": len(dates) >= REQUIRED_SHADOW_DAYS,
        "calendar_days": len(dates),
        "required_calendar_days": REQUIRED_SHADOW_DAYS,
        "first_day": dates[0].isoformat(),
        "last_day": dates[-1].isoformat(),
    }


def validate_shadow_safety(events: list[dict[str, Any]]) -> dict[str, Any]:
    unsafe = []
    for event in events:
        etype = event_type(event)
        payload = event_payload(event)
        if etype in {"BetAccepted", "bet_accepted"}:
            unsafe.append({"event_id": event.get("event_id"), "reason": "accepted_bet_in_shadow_gate"})
        if etype in {"BetSubmitted", "bet_executed"}:
            execution_status = str(payload.get("execution_status", "")).upper()
            shadow_mode = truthy(payload.get("shadow_mode"))
            if execution_status != "SHADOW" and not shadow_mode:
                unsafe.append({"event_id": event.get("event_id"), "reason": "non_shadow_submission"})
    return {"passed": not unsafe, "unsafe_execution_count": len(unsafe), "items": unsafe}


def validate_audit_envelopes(events: list[dict[str, Any]]) -> dict[str, Any]:
    missing_hash = 0
    invalid = []
    for event in events:
        etype = event_type(event)
        if etype not in CHAIN_EVENT_TYPES:
            continue
        try:
            AuditEvent(
                event_id=str(event.get("event_id", "")),
                event_type=str(etype),
                occurred_at_utc=str(event.get("occurred_at_utc", "")),
                race_id=str(event.get("race_id", "")),
                payload=event_payload(event),
                previous_hash=event.get("previous_hash"),
                entry_hash=event.get("entry_hash"),
            ).validate()
        except ValueError as exc:
            invalid.append({"event_id": event.get("event_id"), "reason": str(exc)})
        if not event.get("entry_hash"):
            missing_hash += 1

    return {
        "passed": missing_hash == 0 and not invalid,
        "missing_audit_hash": missing_hash,
        "invalid_envelopes": invalid,
    }


def validate_payload_hashes(events: list[dict[str, Any]]) -> dict[str, Any]:
    missing = []
    for event in events:
        etype = event_type(event)
        if etype not in {"BetSubmitted", "bet_executed"}:
            continue
        payload = event_payload(event)
        missing_fields = [field for field in REQUIRED_HASH_FIELDS if not payload.get(field)]
        if missing_fields:
            missing.append({"event_id": event.get("event_id"), "missing_fields": missing_fields})
    return {"passed": not missing, "missing_payload_hash": len(missing), "items": missing}


def validate_latency(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    p50 = numeric(payload.get("p50"))
    p95 = numeric(payload.get("p95"))
    p99 = numeric(payload.get("p99"))
    p999 = numeric(payload.get("p999"))
    timeout_rate = numeric(payload.get("timeout_rate"))
    baseline_p99 = numeric(payload.get("baseline_p99"))
    latency_regression_rate = None
    if p99 is not None and baseline_p99 is not None and baseline_p99 > 0:
        latency_regression_rate = (p99 / baseline_p99) - 1.0

    failures: list[str] = []
    for key, value in (("p50", p50), ("p95", p95), ("p99", p99), ("p999", p999)):
        if value is None:
            failures.append(f"{key} missing")
        elif value >= LATENCY_THRESHOLDS[key]:
            failures.append(f"{key} >= {LATENCY_THRESHOLDS[key]:g}ms")
    if timeout_rate is None:
        failures.append("timeout_rate missing")
    elif timeout_rate != LATENCY_THRESHOLDS["timeout_rate"]:
        failures.append("timeout_rate > 0")
    if (
        latency_regression_rate is not None
        and latency_regression_rate >= LATENCY_THRESHOLDS["latency_regression_rate"]
    ):
        failures.append("latency_regression_rate >= 30%")

    return {
        "passed": not failures,
        "failures": failures,
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "p999": p999,
        "timeout_rate": timeout_rate,
        "baseline_p99": baseline_p99,
        "latency_regression_rate": (
            round(latency_regression_rate, 6) if latency_regression_rate is not None else None
        ),
        "thresholds": LATENCY_THRESHOLDS,
    }


def _coverage_file_entry(files: dict[str, Any], target: str) -> dict[str, Any] | None:
    normalized_target = target.replace("\\", "/")
    for raw, entry in files.items():
        normalized = raw.replace("\\", "/")
        if normalized == normalized_target or normalized.endswith("/" + normalized_target):
            return entry if isinstance(entry, dict) else None
    return None


def validate_critical_path_coverage(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {
            "passed": False,
            "evidence_present": False,
            "reason": "coverage_json_missing",
            "minimum_branch_coverage_pct": CRITICAL_PATH_BRANCH_COVERAGE_MIN,
            "critical_files": list(CRITICAL_PATH_COVERAGE_FILES),
        }

    payload = load_json(path)
    files = payload.get("files", {}) if isinstance(payload.get("files"), dict) else {}
    missing_files: list[str] = []
    file_summaries: dict[str, Any] = {}
    covered_branches = 0
    total_branches = 0
    covered_lines_pct_values: list[float] = []

    for target in CRITICAL_PATH_COVERAGE_FILES:
        entry = _coverage_file_entry(files, target)
        if entry is None:
            missing_files.append(target)
            continue
        summary = entry.get("summary", {}) if isinstance(entry.get("summary"), dict) else {}
        num_branches = int(summary.get("num_branches", 0) or 0)
        covered = int(summary.get("covered_branches", 0) or 0)
        total_branches += num_branches
        covered_branches += covered
        percent_covered = numeric(summary.get("percent_covered"))
        if percent_covered is not None:
            covered_lines_pct_values.append(percent_covered)
        file_summaries[target] = {
            "num_branches": num_branches,
            "covered_branches": covered,
            "percent_covered": percent_covered,
        }

    if total_branches > 0:
        branch_pct = (covered_branches / total_branches) * 100.0
    elif covered_lines_pct_values:
        branch_pct = min(covered_lines_pct_values)
    else:
        branch_pct = None

    passed = (
        not missing_files
        and branch_pct is not None
        and branch_pct >= CRITICAL_PATH_BRANCH_COVERAGE_MIN
    )
    return {
        "passed": passed,
        "evidence_present": True,
        "coverage_json": str(path),
        "branch_coverage_pct": round(branch_pct, 4) if branch_pct is not None else None,
        "covered_branches": covered_branches,
        "total_branches": total_branches,
        "minimum_branch_coverage_pct": CRITICAL_PATH_BRANCH_COVERAGE_MIN,
        "missing_critical_files": missing_files,
        "files": file_summaries,
    }


def validate_governance_lint() -> dict[str, Any]:
    try:
        from scripts.critical_path_linter import critical_files, scan_file as scan_critical_file
        from scripts.duplicate_impl_detector import find_duplicates
        from scripts.runtime_import_scanner import runtime_files, scan_file as scan_runtime_file

        runtime_violations = []
        for path in runtime_files(ROOT):
            runtime_violations.extend(scan_runtime_file(path))
        critical_violations = []
        for path in critical_files(ROOT):
            critical_violations.extend(scan_critical_file(path))
        duplicates = find_duplicates(ROOT)
        return {
            "passed": not runtime_violations and not critical_violations and not duplicates,
            "runtime_import_violations": runtime_violations,
            "critical_path_violations": critical_violations,
            "duplicate_implementations": duplicates,
        }
    except Exception as exc:
        return {
            "passed": False,
            "runtime_import_violations": [],
            "critical_path_violations": [],
            "duplicate_implementations": {},
            "reason": f"governance lint failed: {exc}",
        }


def load_replay_report(path: Path | None, decision_log: Path, *, require_report: bool = False) -> dict[str, Any]:
    if path and path.exists():
        return load_json(path)
    if require_report:
        raise FileNotFoundError("replay report is required for release/rehearsal Stage 4 gate")
    replay = ReplayEngine(loader=HistoricalSnapshotLoader())
    return replay.replay(decision_log)


def validate_replay(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    checks = {
        "replay_mismatch_count": int(summary.get("replay_mismatch_count", 0)),
        "snapshot_after_decision": int(summary.get("snapshot_after_decision", 0)),
        "missing_hash": int(summary.get("missing_hash", 0)),
        "riskclamp_bypass": int(summary.get("riskclamp_bypass", 0)),
        "stale_data_bet": int(summary.get("stale_data_bet", 0)),
        "missing_audit_hash": int(summary.get("missing_audit_hash", 0)),
        "event_chain_mismatch": int(summary.get("event_chain_mismatch", 0)),
    }
    checks["passed"] = all(value == 0 for value in checks.values())
    return checks


def validate_market_dependency(outdir: Path) -> dict[str, Any]:
    variant_path = outdir / "variant_summary.csv"
    odds_path = outdir / "odds_regime_summary.csv"
    class_path = outdir / "race_class_summary.csv"
    perturbation_path = outdir / "odds_perturbation_summary.csv"
    missing_files = [str(path) for path in (variant_path, odds_path, class_path, perturbation_path) if not path.exists()]
    if missing_files:
        return {"passed": False, "missing_files": missing_files}

    variants = {row.get("variant", ""): row for row in read_csv_rows(variant_path)}
    missing_variants = sorted(REQUIRED_MARKET_VARIANTS - set(variants))
    unavailable = [
        name
        for name in sorted(REQUIRED_MARKET_VARIANTS & set(variants))
        if not truthy(variants[name].get("available", "true"))
    ]
    full = variants.get("full", {})
    market_copy_score = numeric(full.get("market_copy_score"))

    odds_rows = read_csv_rows(odds_path)
    full_bucket_rows = {
        row.get("odds_regime"): row
        for row in odds_rows
        if row.get("variant") == "full" and row.get("odds_regime")
    }
    full_buckets = set(full_bucket_rows)
    missing_buckets = sorted(REQUIRED_ODDS_BUCKETS - full_buckets)
    invalid_buckets = []
    for bucket in sorted(REQUIRED_ODDS_BUCKETS & full_buckets):
        row = full_bucket_rows[bucket]
        bets = numeric(row.get("bets"))
        roi_pct = numeric(row.get("roi_pct"))
        if bets is None or bets <= 0 or roi_pct is None:
            invalid_buckets.append({"odds_regime": bucket, "bets": row.get("bets"), "roi_pct": row.get("roi_pct")})

    class_rows = [row for row in read_csv_rows(class_path) if row.get("variant") == "full"]
    perturbation_rows = read_csv_rows(perturbation_path)
    perturbation_by_scenario = {
        row.get("scenario"): numeric(row.get("avg_abs_market_prob_delta"))
        for row in perturbation_rows
        if row.get("scenario") and row.get("variant") == "full"
    }
    required_perturbations = {"odds_down_10pct", "odds_up_10pct"}
    missing_perturbations = sorted(
        scenario
        for scenario in required_perturbations
        if perturbation_by_scenario.get(scenario) is None
    )
    passed = (
        not missing_variants
        and not unavailable
        and market_copy_score is not None
        and not missing_buckets
        and not invalid_buckets
        and bool(class_rows)
        and not missing_perturbations
    )
    return {
        "passed": passed,
        "missing_variants": missing_variants,
        "unavailable_variants": unavailable,
        "market_copy_score": market_copy_score,
        "missing_odds_buckets": missing_buckets,
        "invalid_odds_buckets": invalid_buckets,
        "race_class_rows": len(class_rows),
        "missing_perturbations": missing_perturbations,
        "odds_perturbation_rows": len(required_perturbations) - len(missing_perturbations),
    }


def evaluate_gate(
    *,
    decision_log: Path,
    latency: Path,
    market_outdir: Path,
    derived_bets: Path,
    coverage_json: Path | None = None,
    replay_report: Path | None = None,
    require_replay_report: bool = False,
) -> GateResult:
    result = GateResult()
    required_paths = {
        "decision_log": decision_log,
        "latency": latency,
        "derived_bets": derived_bets,
    }
    missing = [name for name, path in required_paths.items() if not path.exists()]
    if missing:
        result.fail("required_artifacts", {"missing": missing})
        return result

    events = load_jsonl(decision_log)

    for key, details in {
        "shadow_coverage": validate_shadow_coverage(events),
        "shadow_safety": validate_shadow_safety(events),
        "audit_envelopes": validate_audit_envelopes(events),
        "event_chain": _event_chain_gate(events),
        "payload_hashes": validate_payload_hashes(events),
        "latency": validate_latency(latency),
        "market_dependency": validate_market_dependency(market_outdir),
        "critical_path_coverage": validate_critical_path_coverage(coverage_json),
        "governance_lint": validate_governance_lint(),
    }.items():
        if details.get("passed"):
            result.pass_check(key, details)
        else:
            result.fail(key, details)

    try:
        replay_details = validate_replay(
            load_replay_report(replay_report, decision_log, require_report=require_replay_report)
        )
    except FileNotFoundError as exc:
        replay_details = {"passed": False, "reason": str(exc)}
    if replay_details.get("passed"):
        result.pass_check("replay", replay_details)
    else:
        result.fail("replay", replay_details)

    return result


def _event_chain_gate(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary = ReplayValidator().validate_event_chain(events)
    return {
        "passed": bool(summary.get("valid")) and int(summary.get("bet_submitted", 0)) > 0,
        "riskclamp_bypass": summary.get("riskclamp_bypass", 0),
        "stale_data_bet": summary.get("stale_data_bet", 0),
        "missing_audit_hash": summary.get("missing_audit_hash", 0),
        "chain_mismatch": summary.get("chain_mismatch", 0),
        "bet_submitted": summary.get("bet_submitted", 0),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 4 production-candidate readiness gate")
    parser.add_argument("--decision-log", default="logs/decisions.jsonl")
    parser.add_argument("--latency", default=".ci_latency.json")
    parser.add_argument("--market-outdir", default="results/market_dependency")
    parser.add_argument("--derived-bets", default="derived/bets.csv")
    parser.add_argument("--coverage-json", default="reports/stage4/critical_path_coverage.json")
    parser.add_argument("--replay-report", default=None)
    parser.add_argument(
        "--require-replay-report",
        action="store_true",
        help="Fail instead of falling back to ad-hoc replay generation when replay evidence is missing.",
    )
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = evaluate_gate(
        decision_log=Path(args.decision_log),
        latency=Path(args.latency),
        market_outdir=Path(args.market_outdir),
        derived_bets=Path(args.derived_bets),
        coverage_json=Path(args.coverage_json) if args.coverage_json else None,
        replay_report=Path(args.replay_report) if args.replay_report else None,
        require_replay_report=args.require_replay_report,
    ).to_dict()
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
