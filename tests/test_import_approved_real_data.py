from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.import_approved_real_data import import_approved_real_data


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _valid_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    schedule = tmp_path / "schedule.csv"
    odds = tmp_path / "odds.csv"
    results = tmp_path / "results.csv"
    _write_csv(
        schedule,
        [{"race_id": "R1", "race_start_at_utc": "2026-06-02T03:00:00+00:00", "venue": "TOKYO", "race_number": "01"}],
    )
    _write_csv(
        odds,
        [
            {"race_id": "R1", "horse_id": "H01", "odds": 3.4, "snapshot_at_utc": "2026-06-02T02:55:00+00:00"},
            {"race_id": "R1", "horse_id": "H02", "odds": 7.8, "snapshot_at_utc": "2026-06-02T02:55:00+00:00"},
        ],
    )
    _write_csv(
        results,
        [
            {"race_id": "R1", "horse_id": "H01", "finish_position": 1, "is_win": "true", "win_payout": 340, "result_time_utc": "2026-06-02T03:30:00+00:00"},
            {"race_id": "R1", "horse_id": "H02", "finish_position": 2, "is_win": "false", "win_payout": 0, "result_time_utc": "2026-06-02T03:30:00+00:00"},
        ],
    )
    return schedule, odds, results


def test_import_approved_real_data_writes_live_inputs_and_validates(tmp_path):
    schedule, odds, results = _valid_inputs(tmp_path)

    report = import_approved_real_data(
        schedule_input=schedule,
        odds_input=odds,
        results_input=results,
        output_root=tmp_path / "live_inputs",
        source="jvlink_export",
        clean=True,
        min_races=1,
        min_horses_per_race=2,
    )

    schedule_out = json.loads((tmp_path / "live_inputs" / "today_races.json").read_text(encoding="utf-8"))
    odds_out = json.loads((tmp_path / "live_inputs" / "odds" / "R1.json").read_text(encoding="utf-8"))
    results_out = json.loads((tmp_path / "live_inputs" / "results" / "R1.json").read_text(encoding="utf-8"))

    assert report["passed"] is True
    assert schedule_out[0]["source"] == "jvlink_export"
    assert odds_out[0]["snapshot_at_utc"] == "2026-06-02T02:55:00+00:00"
    assert results_out[0]["result_time_utc"] == "2026-06-02T03:30:00+00:00"


def test_import_approved_real_data_rejects_non_utc_and_mock_source(tmp_path):
    schedule, odds, results = _valid_inputs(tmp_path)
    _write_csv(
        odds,
        [{"race_id": "R1", "horse_id": "H01", "odds": 3.4, "snapshot_at_utc": "2026-06-02T11:55:00+09:00"}],
    )

    with pytest.raises(ValueError, match="must be UTC timezone"):
        import_approved_real_data(
            schedule_input=schedule,
            odds_input=odds,
            results_input=results,
            output_root=tmp_path / "live_inputs",
            source="approved_api",
        )

    _write_csv(
        schedule,
        [{"race_id": "R1", "race_start_at_utc": "2026-06-02T03:00:00+00:00", "source": "mock_api"}],
    )

    with pytest.raises(ValueError, match="source must be one of"):
        import_approved_real_data(
            schedule_input=schedule,
            odds_input=odds,
            results_input=results,
            output_root=tmp_path / "live_inputs",
            source="approved_api",
        )


def test_import_approved_real_data_rejects_missing_horse_and_invalid_odds(tmp_path):
    schedule, odds, results = _valid_inputs(tmp_path)
    _write_csv(
        odds,
        [{"race_id": "R1", "horse_id": "", "odds": 0, "snapshot_at_utc": "2026-06-02T02:55:00+00:00"}],
    )

    with pytest.raises(ValueError, match="missing horse_id"):
        import_approved_real_data(
            schedule_input=schedule,
            odds_input=odds,
            results_input=results,
            output_root=tmp_path / "live_inputs",
            source="manual_verified",
        )

    _write_csv(
        odds,
        [{"race_id": "R1", "horse_id": "H01", "odds": 0, "snapshot_at_utc": "2026-06-02T02:55:00+00:00"}],
    )

    with pytest.raises(ValueError, match="odds must be > 1.0"):
        import_approved_real_data(
            schedule_input=schedule,
            odds_input=odds,
            results_input=results,
            output_root=tmp_path / "live_inputs",
            source="manual_verified",
        )
