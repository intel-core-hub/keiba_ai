from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.bet_types import legs_to_json, normalize_legacy_win_record


AUDIT_TRACE_FIELDS = [
    "decision_id",
    "decision_time_utc",
    "event_id",
    "event_type",
    "occurred_at_utc",
    "entry_hash",
    "previous_hash",
    "bankroll_hash",
    "feature_snapshot_hash",
    "odds_snapshot_hash",
    "model_hash",
    "calibration_hash",
    "policy_hash",
    "risk_limits_hash",
    "execution_status",
    "safe_mode",
    "shadow_mode",
]

OPERATIONAL_REPORT_FIELDS = [
    "timestamp",
    "race_id",
    "selection",
    "selection_id",
    "bet_type",
    "legs",
    "ordered",
    "shadow_only",
    "production_candidate",
    "max_combinations_per_race",
    "max_race_exposure_share",
    "probability",
    "odds",
    "predicted_odds",
    "confirmed_odds",
    "slippage_pct",
    "edge",
    "expected_value",
    "expected_value_per_unit",
    "calibrated_probability",
    "stake",
    "mode",
    "api_status",
    "api_error",
    "hit",
    "payout",
    "profit",
    "bankroll",
    "drawdown",
    "risk_multiplier",
    "lose_streak",
    "win_streak",
    "race_risk_used",
    "risk_clamp_reason",
    "shutdown_state",
    "shutdown_reason",
    "event",
    "model_pkl_sha256",
    "model_version",
    "provider",
]

PREFERRED_FIELDS = AUDIT_TRACE_FIELDS + OPERATIONAL_REPORT_FIELDS


REPORT_EVENT_TYPES = {
    None,
    "bet_executed",
    "bet_settled",
    "BetSubmitted",
    "BetAccepted",
    "BetRejected",
    "RaceSettled",
}


def _flatten_event(record: dict[str, Any]) -> dict[str, Any] | None:
    event_name = record.get("event_type") or record.get("event")
    if event_name not in REPORT_EVENT_TYPES:
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    row = dict(payload)
    occurred_at = record.get("occurred_at_utc") or record.get("timestamp")
    row["event_id"] = row.get("event_id") or record.get("event_id", "")
    row["event_type"] = event_name
    row["occurred_at_utc"] = row.get("occurred_at_utc") or occurred_at
    row["entry_hash"] = row.get("entry_hash") or record.get("entry_hash", "")
    row["previous_hash"] = row.get("previous_hash") or record.get("previous_hash", "")
    row["decision_time_utc"] = row.get("decision_time_utc") or occurred_at
    row.setdefault("race_id", record.get("race_id", ""))
    if event_name in {"BetSubmitted", "bet_executed"} and not row.get("decision_id"):
        raise ValueError("submitted decision event is missing decision_id")
    row.setdefault("decision_id", _decision_id(row))
    row.setdefault("selection_id", row.get("selection", ""))
    row.setdefault("event", event_name)
    row.setdefault("timestamp", occurred_at)
    _enrich_bet_type_fields(row)
    return row


def _enrich_bet_type_fields(row: dict[str, Any]) -> None:
    try:
        normalized = normalize_legacy_win_record(row)
    except ValueError:
        row.setdefault("bet_type", "")
        row.setdefault("legs", "")
        row.setdefault("ordered", "")
        row.setdefault("shadow_only", "")
        row.setdefault("production_candidate", "")
        row.setdefault("max_combinations_per_race", "")
        row.setdefault("max_race_exposure_share", "")
        row.setdefault("payout", row.get("win_payout", ""))
        return

    row["bet_type"] = normalized["bet_type"]
    row["legs"] = legs_to_json(normalized["legs"])
    row["ordered"] = bool(normalized["ordered"])
    row["shadow_only"] = bool(normalized["shadow_only"])
    row["production_candidate"] = bool(normalized["production_candidate"])
    row["max_combinations_per_race"] = normalized["max_combinations_per_race"]
    row["max_race_exposure_share"] = normalized["max_race_exposure_share"]
    row.setdefault("payout", normalized.get("payout", ""))


def _decision_id(row: dict[str, Any]) -> str:
    decision_id = row.get("decision_id")
    if decision_id:
        return str(decision_id)
    race_id = row.get("race_id")
    selection = row.get("selection_id") or row.get("selection")
    if race_id and selection:
        return f"{race_id}:{selection}"
    return ""


def load_rows(jsonl_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            row = _flatten_event(record)
            if row is not None:
                rows.append(row)
    return rows


def write_csv(rows: list[dict[str, Any]], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    extra_fields = sorted({key for row in rows for key in row} - set(PREFERRED_FIELDS))
    fieldnames = list(PREFERRED_FIELDS)
    fieldnames.extend(extra_fields)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def derive(jsonl_path: Path, csv_path: Path) -> int:
    if not jsonl_path.exists():
        raise FileNotFoundError(f"decision JSONL not found: {jsonl_path}")
    rows = load_rows(jsonl_path)
    write_csv(rows, csv_path)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive reporting CSV from canonical decisions.jsonl")
    parser.add_argument("--jsonl", default="logs/decisions.jsonl")
    parser.add_argument("--csv", default="derived/bets.csv")
    args = parser.parse_args()

    count = derive(Path(args.jsonl), Path(args.csv))
    print(f"Derived {count} rows from {args.jsonl} into {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
