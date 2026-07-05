from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def load_feature_snapshots(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows
    for path in sorted(root.rglob("*.jsonl")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            features = record.get("features", {})
            if not isinstance(features, dict):
                features = {}
            row = {
                "race_id": record.get("race_id", ""),
                "horse_id": record.get("horse_id", ""),
                "snapshot_time_utc": record.get("snapshot_time_utc", ""),
                "source_cutoff_time_utc": record.get("source_cutoff_time_utc", ""),
                "feature_version": record.get("feature_version", ""),
                "source_file": str(path),
                "source_line": line_no,
            }
            row.update(features)
            rows.append(row)
    return rows


def load_decision_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        event_type = record.get("event_type") or record.get("event")
        if event_type not in {"BetSubmitted", "bet_executed"}:
            continue
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else record
        rows.append(
            {
                "race_id": payload.get("race_id") or record.get("race_id", ""),
                "horse_id": payload.get("selection_id") or payload.get("selection") or payload.get("horse_id") or "",
                "occurred_at_utc": record.get("occurred_at_utc") or payload.get("decision_time_utc") or payload.get("timestamp") or "",
            }
        )
    return rows


def load_result_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))
