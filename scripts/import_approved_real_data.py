from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.validate_live_inputs import validate_live_inputs


ALLOWED_SOURCES = {"jvlink_export", "approved_api", "manual_verified"}
BANNED_SOURCE_MARKERS = {"mock", "copied", "copy", "backdated", "synthetic", "fixture"}


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            for key in ("races", "schedule", "odds", "results"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
        if not isinstance(payload, list):
            raise ValueError(f"{path}: JSON input must be a list or object containing a list")
        return payload
    raise ValueError(f"{path}: unsupported input format; use .csv, .json, or .jsonl")


def _required_text(row: dict[str, Any], field: str, *, kind: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise ValueError(f"{kind} row missing {field}")
    return value


def _utc_iso(value: Any, *, field: str, kind: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{kind} row missing {field}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{kind} {field} must be ISO8601: {text}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{kind} {field} must include timezone: {text}")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{kind} {field} must be UTC timezone: {text}")
    return parsed.astimezone(timezone.utc).isoformat()


def _source(row: dict[str, Any], default_source: str, *, kind: str) -> str:
    source = str(row.get("source") or default_source).strip()
    normalized = source.lower()
    if normalized not in ALLOWED_SOURCES:
        raise ValueError(f"{kind} source must be one of {sorted(ALLOWED_SOURCES)}: {source}")
    if any(marker in normalized for marker in BANNED_SOURCE_MARKERS):
        raise ValueError(f"{kind} source is not approved real-data evidence: {source}")
    return normalized


def _float_gt_one(value: Any, *, field: str, kind: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{kind} {field} must be numeric: {value}") from exc
    if parsed <= 1.0:
        raise ValueError(f"{kind} {field} must be > 1.0: {parsed}")
    return parsed


def _optional_int(value: Any, *, field: str, kind: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{kind} {field} must be an integer: {value}") from exc


def _bool(value: Any, *, kind: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "win", "winner"}:
        return True
    if text in {"0", "false", "no", "n", "lose", "lost"}:
        return False
    raise ValueError(f"{kind} is_win must be boolean-like: {value}")


def _clean_json_files(*directories: Path) -> None:
    for directory in directories:
        if directory.exists():
            for path in directory.glob("*.json"):
                path.unlink()


def import_approved_real_data(
    *,
    schedule_input: Path,
    odds_input: Path,
    results_input: Path,
    output_root: Path,
    source: str,
    clean: bool = False,
    min_races: int = 1,
    min_horses_per_race: int = 2,
) -> dict[str, Any]:
    default_source = _source({"source": source}, source, kind="config")
    schedule_rows = _normalize_schedule(_read_records(schedule_input), default_source)
    odds_rows = _normalize_odds(_read_records(odds_input), default_source)
    result_rows = _normalize_results(_read_records(results_input), default_source)

    schedule_ids = {row["race_id"] for row in schedule_rows}
    for row in odds_rows:
        if row["race_id"] not in schedule_ids:
            raise ValueError(f"odds race_id has no schedule row: {row['race_id']}")
    for row in result_rows:
        if row["race_id"] not in schedule_ids:
            raise ValueError(f"result race_id has no schedule row: {row['race_id']}")

    odds_by_race: dict[str, list[dict[str, Any]]] = defaultdict(list)
    results_by_race: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in odds_rows:
        odds_by_race[row["race_id"]].append(row)
    for row in result_rows:
        results_by_race[row["race_id"]].append(row)

    if clean:
        _clean_json_files(output_root / "odds", output_root / "results")
    (output_root / "odds").mkdir(parents=True, exist_ok=True)
    (output_root / "results").mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    (output_root / "today_races.json").write_text(
        json.dumps(schedule_rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for race_id, rows in sorted(odds_by_race.items()):
        (output_root / "odds" / f"{race_id}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    for race_id, rows in sorted(results_by_race.items()):
        (output_root / "results" / f"{race_id}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    validation = validate_live_inputs(
        schedule=output_root / "today_races.json",
        odds_dir=output_root / "odds",
        min_races=min_races,
        min_horses_per_race=min_horses_per_race,
    )
    if not validation["passed"]:
        raise ValueError("imported live inputs failed validation: " + "; ".join(validation["errors"]))
    return {
        "passed": True,
        "source": default_source,
        "output_root": str(output_root),
        "schedule_rows": len(schedule_rows),
        "odds_rows": len(odds_rows),
        "result_rows": len(result_rows),
        "validation": validation,
    }


def _normalize_schedule(rows: list[dict[str, Any]], default_source: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        race_id = _required_text(row, "race_id", kind="schedule")
        if race_id in seen:
            raise ValueError(f"duplicate schedule race_id: {race_id}")
        seen.add(race_id)
        normalized.append(
            {
                "race_id": race_id,
                "race_start_at_utc": _utc_iso(row.get("race_start_at_utc"), field="race_start_at_utc", kind="schedule"),
                "venue": str(row.get("venue") or ""),
                "race_number": str(row.get("race_number") or ""),
                "source": _source(row, default_source, kind="schedule"),
            }
        )
    return normalized


def _normalize_odds(rows: list[dict[str, Any]], default_source: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        race_id = _required_text(row, "race_id", kind="odds")
        horse_id = _required_text(row, "horse_id", kind="odds")
        key = (race_id, horse_id)
        if key in seen:
            raise ValueError(f"duplicate odds row: {race_id}/{horse_id}")
        seen.add(key)
        normalized.append(
            {
                "race_id": race_id,
                "horse_id": horse_id,
                "odds": _float_gt_one(row.get("odds"), field="odds", kind="odds"),
                "snapshot_at_utc": _utc_iso(row.get("snapshot_at_utc") or row.get("snapshot_time"), field="snapshot_at_utc", kind="odds"),
                "source": _source(row, default_source, kind="odds"),
            }
        )
    return normalized


def _normalize_results(rows: list[dict[str, Any]], default_source: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        race_id = _required_text(row, "race_id", kind="result")
        horse_id = _required_text(row, "horse_id", kind="result")
        key = (race_id, horse_id)
        if key in seen:
            raise ValueError(f"duplicate result row: {race_id}/{horse_id}")
        seen.add(key)
        normalized.append(
            {
                "race_id": race_id,
                "horse_id": horse_id,
                "finish_position": _optional_int(row.get("finish_position"), field="finish_position", kind="result"),
                "is_win": _bool(row.get("is_win"), kind="result"),
                "win_payout": float(row.get("win_payout") or 0),
                "result_time_utc": _utc_iso(row.get("result_time_utc") or row.get("result_time"), field="result_time_utc", kind="result"),
                "source": _source(row, default_source, kind="result"),
            }
        )
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import approved real data exports into data/live_inputs")
    parser.add_argument("--schedule-input", required=True)
    parser.add_argument("--odds-input", required=True)
    parser.add_argument("--results-input", required=True)
    parser.add_argument("--output-root", default="data/live_inputs")
    parser.add_argument("--source", choices=sorted(ALLOWED_SOURCES), required=True)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--min-races", type=int, default=1)
    parser.add_argument("--min-horses-per-race", type=int, default=2)
    parser.add_argument("--status", default="reports/data_collection/import_approved_real_data_status.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = import_approved_real_data(
            schedule_input=Path(args.schedule_input),
            odds_input=Path(args.odds_input),
            results_input=Path(args.results_input),
            output_root=Path(args.output_root),
            source=args.source,
            clean=args.clean,
            min_races=args.min_races,
            min_horses_per_race=args.min_horses_per_race,
        )
    except Exception as exc:
        report = {"passed": False, "error": str(exc)}
        status_path = Path(args.status)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    status_path = Path(args.status)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
