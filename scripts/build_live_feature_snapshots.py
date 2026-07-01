from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.betting.bet_types import normalize_legacy_win_record
from core.data_sources.feature_snapshot_store import FeatureSnapshotStore
from core.data_sources.local_file_provider import parse_utc_datetime
from scripts.validate_live_inputs import validate_live_inputs


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _schedule_by_race(path: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError("schedule JSON must be a list")
    rows: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("schedule row must be an object")
        race_id = str(item.get("race_id") or "").strip()
        if not race_id:
            raise ValueError("schedule row missing race_id")
        rows[race_id] = item
    return rows


def _odds_rows(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, dict):
        payload = payload.get("odds") if "odds" in payload else [payload]
    if not isinstance(payload, list):
        raise ValueError(f"odds JSON must be a list or object: {path}")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"odds row must be an object: {path}")
        if not item.get("bet_type") and not item.get("legs") and not (item.get("horse_id") or item.get("selection_id")):
            raise ValueError(f"odds row missing horse_id: {path}")
        try:
            normalized = normalize_legacy_win_record({**item, "race_id": item.get("race_id") or path.stem})
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
        item = dict(item)
        item.setdefault("horse_id", normalized["legs"][0])
        item["bet_type"] = normalized["bet_type"]
        item["legs"] = normalized["legs"]
        rows.append(item)
    return rows


def _float(value: Any, *, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric: {value}") from exc


def _snapshot_time(row: dict[str, Any], fallback: datetime) -> datetime:
    value = row.get("snapshot_at_utc") or row.get("snapshot_time")
    if value in (None, ""):
        return fallback
    return parse_utc_datetime(value, field="snapshot_time")


def _market_features(row: dict[str, Any], *, favorite_rank: int, field_size: int) -> dict[str, float | int]:
    odds = _float(row.get("odds"), field="odds")
    market_support = round(min(1.0, max(0.001, 1.0 / max(odds, 1e-9))), 6)
    rank_score = round(1.0 - ((favorite_rank - 1) / max(field_size - 1, 1)), 6)
    return {
        "odds_value": market_support,
        "favorite_rank": favorite_rank,
        "distance": 0.0,
        "market_support": market_support,
        "public_confidence": 0.0,
        "track_affinity": 0.5,
        "distance_affinity": 0.5,
        "weather_affinity": 0.5,
        "pace_affinity": 0.5,
        "rank_score": rank_score,
    }


def _existing_snapshot_keys(output_root: Path) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    if not output_root.exists():
        return keys
    for path in output_root.rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            keys.add(
                (
                    str(record.get("race_id") or ""),
                    str(record.get("horse_id") or ""),
                    str(record.get("snapshot_time_utc") or ""),
                    str(record.get("feature_version") or ""),
                )
            )
    return keys


def build_feature_snapshots(
    *,
    schedule: Path,
    odds_dir: Path,
    output_root: Path,
    snapshot_time_utc: datetime | None,
    feature_version: str,
    validate_min_races: int | None = None,
    validate_min_horses_per_race: int | None = None,
) -> dict[str, Any]:
    if validate_min_races is not None or validate_min_horses_per_race is not None:
        validation = validate_live_inputs(
            schedule=schedule,
            odds_dir=odds_dir,
            min_races=validate_min_races or 1,
            min_horses_per_race=validate_min_horses_per_race or 1,
        )
        if not validation["passed"]:
            raise ValueError("live input validation failed: " + "; ".join(validation["errors"]))

    races = _schedule_by_race(schedule)
    store = FeatureSnapshotStore(output_root)
    existing = _existing_snapshot_keys(output_root)
    written = 0
    skipped_duplicate = 0
    race_count = 0

    for odds_path in sorted(odds_dir.glob("*.json")):
        race_id = odds_path.stem
        race = races.get(race_id)
        if race is None:
            raise ValueError(f"odds fixture has no schedule row: {race_id}")
        rows = _odds_rows(odds_path)
        ranked = sorted(rows, key=lambda item: (_float(item.get("odds"), field="odds"), str(item.get("horse_id") or "")))
        ranks = {id(item): rank for rank, item in enumerate(ranked, start=1)}
        field_size = len(rows)
        race_start = parse_utc_datetime(race.get("race_start_at_utc"), field="race_start_at_utc")
        race_count += 1

        for row in rows:
            observed_at = snapshot_time_utc or _snapshot_time(row, race_start)
            horse_id = str(row.get("horse_id") or row.get("selection_id") or "").strip()
            key = (race_id, horse_id, observed_at.isoformat(), feature_version)
            if key in existing:
                skipped_duplicate += 1
                continue
            store.save(
                race_id=race_id,
                horse_id=horse_id,
                features=_market_features(row, favorite_rank=ranks[id(row)], field_size=field_size),
                source_cutoff_time_utc=observed_at,
                snapshot_time_utc=observed_at,
                feature_version=feature_version,
            )
            existing.add(key)
            written += 1

    return {
        "passed": True,
        "schedule": str(schedule),
        "odds_dir": str(odds_dir),
        "output_root": str(output_root),
        "races_seen": race_count,
        "snapshots_written": written,
        "skipped_duplicate": skipped_duplicate,
        "feature_version": feature_version,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build feature snapshots from approved live schedule and odds files")
    parser.add_argument("--schedule", default="data/live_inputs/today_races.json")
    parser.add_argument("--odds-dir", default="data/live_inputs/odds")
    parser.add_argument("--output-root", default="data/feature_snapshots")
    parser.add_argument("--snapshot-time-utc", default=None)
    parser.add_argument("--feature-version", default="live_market_v1")
    parser.add_argument("--validate-min-races", type=int, default=None)
    parser.add_argument("--validate-min-horses-per-race", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot_time = (
        parse_utc_datetime(args.snapshot_time_utc, field="snapshot_time_utc")
        if args.snapshot_time_utc
        else None
    )
    try:
        report = build_feature_snapshots(
            schedule=Path(args.schedule),
            odds_dir=Path(args.odds_dir),
            output_root=Path(args.output_root),
            snapshot_time_utc=snapshot_time,
            feature_version=args.feature_version,
            validate_min_races=args.validate_min_races,
            validate_min_horses_per_race=args.validate_min_horses_per_race,
        )
    except ValueError as exc:
        report = {"passed": False, "error": str(exc)}
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
