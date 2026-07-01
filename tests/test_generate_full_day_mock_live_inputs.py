from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.generate_full_day_mock_live_inputs import generate_full_day_mock_live_inputs
from scripts.validate_live_inputs import validate_live_inputs


def test_generate_full_day_mock_live_inputs_creates_valid_full_day(tmp_path):
    report = generate_full_day_mock_live_inputs(
        output_root=tmp_path / "live_inputs",
        race_count=3,
        horses_per_race=5,
        start_at_utc=datetime(2026, 6, 2, 3, 0, tzinfo=timezone.utc),
        interval_minutes=30,
        clean=False,
    )

    schedule = json.loads((tmp_path / "live_inputs" / "today_races.json").read_text(encoding="utf-8"))
    odds = json.loads((tmp_path / "live_inputs" / "odds" / schedule[0]["race_id"]).with_suffix(".json").read_text(encoding="utf-8"))
    results = json.loads((tmp_path / "live_inputs" / "results" / schedule[0]["race_id"]).with_suffix(".json").read_text(encoding="utf-8"))
    validation = validate_live_inputs(
        schedule=tmp_path / "live_inputs" / "today_races.json",
        odds_dir=tmp_path / "live_inputs" / "odds",
        min_races=3,
        min_horses_per_race=5,
    )

    assert report["total_horses"] == 15
    assert len(schedule) == 3
    assert len(odds) == 5
    assert len(results) == 5
    assert validation["passed"] is True


def test_generate_full_day_mock_live_inputs_can_clean_stale_files(tmp_path):
    stale = tmp_path / "live_inputs" / "odds" / "STALE.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("[]", encoding="utf-8")

    generate_full_day_mock_live_inputs(
        output_root=tmp_path / "live_inputs",
        race_count=1,
        horses_per_race=5,
        start_at_utc=datetime(2026, 6, 2, 3, 0, tzinfo=timezone.utc),
        interval_minutes=30,
        clean=True,
    )

    assert not stale.exists()
