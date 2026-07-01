from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _race_id(index: int) -> str:
    return f"MOCK20260602R{index:02d}"


def generate_full_day_mock_live_inputs(
    *,
    output_root: Path,
    race_count: int,
    horses_per_race: int,
    start_at_utc: datetime,
    interval_minutes: int,
    clean: bool = False,
) -> dict[str, Any]:
    if race_count <= 0:
        raise ValueError("race_count must be positive")
    if horses_per_race <= 0:
        raise ValueError("horses_per_race must be positive")

    schedule: list[dict[str, Any]] = []
    odds_dir = output_root / "odds"
    results_dir = output_root / "results"
    if clean:
        for directory in (odds_dir, results_dir):
            if directory.exists():
                for path in directory.glob("*.json"):
                    path.unlink()
    odds_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    for race_index in range(1, race_count + 1):
        race_id = _race_id(race_index)
        start = start_at_utc + timedelta(minutes=interval_minutes * (race_index - 1))
        schedule.append(
            {
                "race_id": race_id,
                "race_start_at_utc": _iso(start),
                "venue": "MOCK",
                "race_number": f"{race_index:02d}",
                "source": "full_day_mock_fixture",
            }
        )

        odds_rows: list[dict[str, Any]] = []
        result_rows: list[dict[str, Any]] = []
        winner_index = ((race_index - 1) % horses_per_race) + 1
        for horse_index in range(1, horses_per_race + 1):
            horse_id = f"H{horse_index:02d}"
            odds = round(1.6 + horse_index * 0.75 + (race_index % 4) * 0.12, 2)
            finish_position = ((horse_index - winner_index) % horses_per_race) + 1
            odds_rows.append(
                {
                    "race_id": race_id,
                    "horse_id": horse_id,
                    "odds": odds,
                    "snapshot_at_utc": _iso(start - timedelta(minutes=5)),
                    "source": "full_day_mock_fixture",
                }
            )
            result_rows.append(
                {
                    "race_id": race_id,
                    "horse_id": horse_id,
                    "finish_position": finish_position,
                    "is_win": finish_position == 1,
                    "win_payout": int(odds * 100) if finish_position == 1 else 0,
                    "result_time_utc": _iso(start + timedelta(minutes=30)),
                    "source": "full_day_mock_fixture",
                }
            )
        (odds_dir / f"{race_id}.json").write_text(
            json.dumps(odds_rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (results_dir / f"{race_id}.json").write_text(
            json.dumps(result_rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "today_races.json").write_text(
        json.dumps(schedule, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "passed": True,
        "output_root": str(output_root),
        "schedule": str(output_root / "today_races.json"),
        "odds_dir": str(odds_dir),
        "results_dir": str(results_dir),
        "race_count": race_count,
        "horses_per_race": horses_per_race,
        "total_horses": race_count * horses_per_race,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate full-day mock live inputs for gateway dry-runs")
    parser.add_argument("--output-root", default="data/live_inputs")
    parser.add_argument("--race-count", type=int, default=12)
    parser.add_argument("--horses-per-race", type=int, default=8)
    parser.add_argument("--start-at-utc", default="2026-06-02T03:00:00+00:00")
    parser.add_argument("--interval-minutes", type=int, default=30)
    parser.add_argument("--clean", action="store_true", help="remove existing odds/results JSON fixtures first")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    start = datetime.fromisoformat(args.start_at_utc.replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError("start-at-utc must include timezone")
    report = generate_full_day_mock_live_inputs(
        output_root=Path(args.output_root),
        race_count=args.race_count,
        horses_per_race=args.horses_per_race,
        start_at_utc=start.astimezone(timezone.utc),
        interval_minutes=args.interval_minutes,
        clean=args.clean,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
