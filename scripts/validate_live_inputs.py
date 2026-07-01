from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.bet_types import normalize_legacy_win_record


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_rows(payload: Any, *, field: str, kind: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get(field) if field in payload else [payload]
    else:
        raise ValueError(f"{kind} JSON must be a list, object, or object with '{field}' list")
    if not isinstance(rows, list):
        raise ValueError(f"{kind} JSON '{field}' must be a list")
    return rows


def _race_ids(schedule_path: Path) -> list[str]:
    payload = _load_json(schedule_path)
    if not isinstance(payload, list):
        raise ValueError("schedule JSON must be a list")
    race_ids: list[str] = []
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"schedule row {idx} must be an object")
        race_id = str(item.get("race_id") or "").strip()
        if not race_id:
            raise ValueError(f"schedule row {idx} missing race_id")
        race_ids.append(race_id)
    return race_ids


def _validate_odds_file(path: Path, *, expected_race_id: str, min_horses_per_race: int) -> tuple[int, list[str]]:
    errors: list[str] = []
    payload = _load_json(path)
    try:
        payload_rows = _extract_rows(payload, field="odds", kind="odds")
    except ValueError as exc:
        return 0, [f"{path}: {exc}"]
    seen_horses: set[str] = set()
    seen_keys: set[tuple[str, tuple[str, ...]]] = set()
    for idx, item in enumerate(payload_rows, start=1):
        if not isinstance(item, dict):
            errors.append(f"{path}: row {idx} must be an object")
            continue
        race_id = str(item.get("race_id") or expected_race_id).strip()
        if race_id != expected_race_id:
            errors.append(f"{path}: row {idx} race_id {race_id!r} != {expected_race_id!r}")
        if not item.get("bet_type") and not item.get("legs") and not (item.get("horse_id") or item.get("selection_id")):
            errors.append(f"{path}: row {idx} missing horse_id")
            continue
        try:
            normalized = normalize_legacy_win_record({**item, "race_id": race_id})
        except ValueError as exc:
            errors.append(f"{path}: row {idx} {exc}")
            continue
        key = (normalized["bet_type"], tuple(normalized["legs"]))
        if key in seen_keys:
            errors.append(f"{path}: duplicate odds row {normalized['bet_type']} {normalized['legs']!r}")
        seen_keys.add(key)
        for horse_id in normalized["legs"]:
            seen_horses.add(horse_id)
        try:
            odds = float(item.get("odds"))
        except (TypeError, ValueError):
            errors.append(f"{path}: row {idx} odds must be numeric")
            continue
        if odds <= 1.0:
            errors.append(f"{path}: row {idx} odds must be > 1.0")
    if len(seen_horses) < min_horses_per_race:
        errors.append(
            f"{path}: horse_count {len(seen_horses)} < min_horses_per_race {min_horses_per_race}"
        )
    return len(seen_horses), errors


def validate_live_inputs(
    *,
    schedule: Path,
    odds_dir: Path,
    min_races: int,
    min_horses_per_race: int,
) -> dict[str, Any]:
    errors: list[str] = []
    race_ids = _race_ids(schedule)
    schedule_set = set(race_ids)
    odds_files = {path.stem: path for path in odds_dir.glob("*.json")} if odds_dir.exists() else {}
    race_summaries: list[dict[str, Any]] = []

    if len(race_ids) < min_races:
        errors.append(f"race_count {len(race_ids)} < min_races {min_races}")
    duplicate_races = sorted({race_id for race_id in race_ids if race_ids.count(race_id) > 1})
    for race_id in duplicate_races:
        errors.append(f"duplicate race_id {race_id!r} in schedule")

    for race_id in race_ids:
        path = odds_files.get(race_id)
        if path is None:
            errors.append(f"missing odds file for race_id {race_id!r}")
            race_summaries.append({"race_id": race_id, "horse_count": 0, "odds_file": None})
            continue
        horse_count, file_errors = _validate_odds_file(
            path,
            expected_race_id=race_id,
            min_horses_per_race=min_horses_per_race,
        )
        errors.extend(file_errors)
        race_summaries.append({"race_id": race_id, "horse_count": horse_count, "odds_file": str(path)})

    extra_odds = sorted(set(odds_files) - schedule_set)
    for race_id in extra_odds:
        errors.append(f"odds file has no schedule race_id {race_id!r}: {odds_files[race_id]}")

    return {
        "passed": not errors,
        "schedule": str(schedule),
        "odds_dir": str(odds_dir),
        "race_count": len(race_ids),
        "total_horses": sum(item["horse_count"] for item in race_summaries),
        "min_races": min_races,
        "min_horses_per_race": min_horses_per_race,
        "races": race_summaries,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate approved live schedule and odds files before drift analysis")
    parser.add_argument("--schedule", default="data/live_inputs/today_races.json")
    parser.add_argument("--odds-dir", default="data/live_inputs/odds")
    parser.add_argument("--min-races", type=int, default=1)
    parser.add_argument("--min-horses-per-race", type=int, default=2)
    parser.add_argument("--status", default="reports/data_collection/live_input_validation.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_live_inputs(
        schedule=Path(args.schedule),
        odds_dir=Path(args.odds_dir),
        min_races=args.min_races,
        min_horses_per_race=args.min_horses_per_race,
    )
    status_path = Path(args.status)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
