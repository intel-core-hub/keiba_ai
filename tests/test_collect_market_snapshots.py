from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scripts.collect_market_snapshots import collect_market_snapshots


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _args(tmp_path: Path, **overrides) -> argparse.Namespace:
    defaults = {
        "provider": "local_file",
        "schedule": str(tmp_path / "today_races.json"),
        "odds_dir": str(tmp_path / "odds"),
        "early_minutes_before": 30.0,
        "closing_minutes_before": 5.0,
        "window_minutes": 3.0,
        "early_output": str(tmp_path / "market" / "early_odds.csv"),
        "closing_output": str(tmp_path / "market" / "closing_odds.csv"),
        "status": str(tmp_path / "reports" / "collection_status.json"),
        "errors": str(tmp_path / "reports" / "collection_errors.jsonl"),
        "now": "2026-06-02T01:00:00+00:00",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_collect_market_snapshots_writes_windowed_early_and_closing_without_duplicates(tmp_path):
    _write_json(
        tmp_path / "today_races.json",
        [
            {"race_id": "R_EARLY", "race_start_at_utc": "2026-06-02T01:30:00+00:00", "venue": "TOKYO", "race_number": "01", "source": "local_file"},
            {"race_id": "R_CLOSE", "race_start_at_utc": "2026-06-02T01:05:00+00:00", "venue": "TOKYO", "race_number": "02", "source": "local_file"},
            {"race_id": "R_LATER", "race_start_at_utc": "2026-06-02T03:00:00+00:00", "venue": "TOKYO", "race_number": "03", "source": "local_file"},
        ],
    )
    _write_json(tmp_path / "odds" / "R_EARLY.json", [{"horse_id": "H01", "odds": 3.6}])
    _write_json(tmp_path / "odds" / "R_CLOSE.json", [{"horse_id": "H02", "odds": 7.8}])

    status = collect_market_snapshots(_args(tmp_path))
    status_again = collect_market_snapshots(_args(tmp_path))

    early_rows = list(csv.DictReader((tmp_path / "market" / "early_odds.csv").open(newline="", encoding="utf-8")))
    closing_rows = list(csv.DictReader((tmp_path / "market" / "closing_odds.csv").open(newline="", encoding="utf-8")))
    assert status["counts"]["written"] == {"early": 1, "closing": 1}
    assert status_again["counts"]["skipped_duplicate"] == {"early": 1, "closing": 1}
    assert len(early_rows) == 1
    assert len(closing_rows) == 1
    assert early_rows[0]["snapshot_time"] == "2026-06-02T01:00:00+00:00"
    assert closing_rows[0]["snapshot_time"] == "2026-06-02T01:00:00+00:00"


def test_collect_market_snapshots_records_invalid_rows_and_provider_failures(tmp_path):
    _write_json(
        tmp_path / "today_races.json",
        [
            {"race_id": "R_BAD", "race_start_at_utc": "2026-06-02T01:30:00+00:00", "source": "local_file"},
            {"race_id": "R_MISSING", "race_start_at_utc": "2026-06-02T01:30:00+00:00", "source": "local_file"},
        ],
    )
    _write_json(tmp_path / "odds" / "R_BAD.json", [{"horse_id": "H01", "odds": 0}])

    status = collect_market_snapshots(_args(tmp_path))

    error_lines = [
        json.loads(line)
        for line in (tmp_path / "reports" / "collection_errors.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert status["passed"] is False
    assert {item["reason"] for item in error_lines} == {"invalid_odds", "provider_error"}
    assert not (tmp_path / "market" / "early_odds.csv").exists()
