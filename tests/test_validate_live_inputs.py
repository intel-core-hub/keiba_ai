from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_live_inputs import validate_live_inputs


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_validate_live_inputs_passes_complete_schedule_and_odds(tmp_path):
    _write_json(
        tmp_path / "today_races.json",
        [
            {"race_id": "R1", "race_start_at_utc": "2026-06-02T03:00:00+00:00"},
            {"race_id": "R2", "race_start_at_utc": "2026-06-02T04:00:00+00:00"},
        ],
    )
    _write_json(
        tmp_path / "odds" / "R1.json",
        [{"race_id": "R1", "horse_id": "H01", "odds": 3.4}, {"race_id": "R1", "horse_id": "H02", "odds": 7.8}],
    )
    _write_json(
        tmp_path / "odds" / "R2.json",
        [{"race_id": "R2", "horse_id": "H03", "odds": 2.4}, {"race_id": "R2", "horse_id": "H04", "odds": 5.8}],
    )

    report = validate_live_inputs(
        schedule=tmp_path / "today_races.json",
        odds_dir=tmp_path / "odds",
        min_races=2,
        min_horses_per_race=2,
    )

    assert report["passed"] is True
    assert report["race_count"] == 2
    assert report["total_horses"] == 4


def test_validate_live_inputs_fails_missing_race_and_bad_odds(tmp_path):
    _write_json(
        tmp_path / "today_races.json",
        [
            {"race_id": "R1", "race_start_at_utc": "2026-06-02T03:00:00+00:00"},
            {"race_id": "R2", "race_start_at_utc": "2026-06-02T04:00:00+00:00"},
        ],
    )
    _write_json(
        tmp_path / "odds" / "R1.json",
        [{"race_id": "R1", "horse_id": "H01", "odds": 1.0}],
    )
    _write_json(tmp_path / "odds" / "EXTRA.json", [{"race_id": "EXTRA", "horse_id": "H99", "odds": 9.9}])

    report = validate_live_inputs(
        schedule=tmp_path / "today_races.json",
        odds_dir=tmp_path / "odds",
        min_races=3,
        min_horses_per_race=2,
    )

    assert report["passed"] is False
    assert any("race_count 2 < min_races 3" in item for item in report["errors"])
    assert any("missing odds file for race_id 'R2'" in item for item in report["errors"])
    assert any("odds must be > 1.0" in item for item in report["errors"])
    assert any("odds file has no schedule race_id 'EXTRA'" in item for item in report["errors"])
