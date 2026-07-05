from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_live_feature_snapshots import build_feature_snapshots


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_build_live_feature_snapshots_writes_all_horses_ranked_by_odds(tmp_path):
    _write_json(
        tmp_path / "today_races.json",
        [{"race_id": "R1", "race_start_at_utc": "2026-06-02T03:00:00+00:00"}],
    )
    _write_json(
        tmp_path / "odds" / "R1.json",
        [
            {"race_id": "R1", "horse_id": "H02", "odds": 7.8},
            {"race_id": "R1", "horse_id": "H01", "odds": 3.4},
        ],
    )

    report = build_feature_snapshots(
        schedule=tmp_path / "today_races.json",
        odds_dir=tmp_path / "odds",
        output_root=tmp_path / "feature_snapshots",
        snapshot_time_utc=None,
        feature_version="test_v1",
    )

    path = tmp_path / "feature_snapshots" / "2026-06-02" / "R1.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert report["snapshots_written"] == 2
    assert rows[0]["horse_id"] == "H02"
    assert rows[0]["features"]["favorite_rank"] == 2
    assert rows[1]["horse_id"] == "H01"
    assert rows[1]["features"]["favorite_rank"] == 1
    assert rows[1]["features"]["odds_value"] == rows[1]["features"]["market_support"]

    report_again = build_feature_snapshots(
        schedule=tmp_path / "today_races.json",
        odds_dir=tmp_path / "odds",
        output_root=tmp_path / "feature_snapshots",
        snapshot_time_utc=None,
        feature_version="test_v1",
    )

    rows_again = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert report_again["snapshots_written"] == 0
    assert report_again["skipped_duplicate"] == 2
    assert len(rows_again) == 2


def test_build_live_feature_snapshots_can_require_full_day_thresholds(tmp_path):
    _write_json(
        tmp_path / "today_races.json",
        [{"race_id": "R1", "race_start_at_utc": "2026-06-02T03:00:00+00:00"}],
    )
    _write_json(
        tmp_path / "odds" / "R1.json",
        [{"race_id": "R1", "horse_id": "H01", "odds": 3.4}, {"race_id": "R1", "horse_id": "H02", "odds": 7.8}],
    )

    with pytest.raises(ValueError, match="live input validation failed"):
        build_feature_snapshots(
            schedule=tmp_path / "today_races.json",
            odds_dir=tmp_path / "odds",
            output_root=tmp_path / "feature_snapshots",
            snapshot_time_utc=None,
            feature_version="test_v1",
            validate_min_races=12,
            validate_min_horses_per_race=5,
        )
