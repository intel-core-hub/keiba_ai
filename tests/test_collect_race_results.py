from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scripts.collect_race_results import collect_race_results


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _args(tmp_path: Path, **overrides) -> argparse.Namespace:
    defaults = {
        "provider": "local_file",
        "schedule": str(tmp_path / "today_races.json"),
        "results_dir": str(tmp_path / "results"),
        "output": str(tmp_path / "data" / "race_results.csv"),
        "status": str(tmp_path / "reports" / "result_status.json"),
        "errors": str(tmp_path / "reports" / "result_errors.jsonl"),
        "now": "2026-06-02T05:00:00+00:00",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_collect_race_results_appends_and_deduplicates(tmp_path):
    _write_json(
        tmp_path / "today_races.json",
        [{"race_id": "R1", "race_start_at_utc": "2026-06-02T01:30:00+00:00", "source": "local_file"}],
    )
    _write_json(
        tmp_path / "results" / "R1.json",
        [
            {"horse_id": "H01", "finish_position": 1, "is_win": True, "win_payout": 360},
            {"horse_id": "H02", "finish_position": 5, "is_win": "false", "win_payout": 0},
        ],
    )

    first = collect_race_results(_args(tmp_path))
    second = collect_race_results(_args(tmp_path))

    rows = list(csv.DictReader((tmp_path / "data" / "race_results.csv").open(newline="", encoding="utf-8")))
    assert first["counts"]["written"] == 2
    assert second["counts"]["skipped_duplicate"] == 2
    assert rows[0]["is_win"] == "true"
    assert rows[1]["is_win"] == "false"
    assert rows[0]["result_time"] == "2026-06-02T05:00:00+00:00"


def test_collect_race_results_rejects_negative_payout(tmp_path):
    _write_json(
        tmp_path / "today_races.json",
        [{"race_id": "R1", "race_start_at_utc": "2026-06-02T01:30:00+00:00", "source": "local_file"}],
    )
    _write_json(
        tmp_path / "results" / "R1.json",
        [{"horse_id": "H01", "finish_position": 1, "is_win": True, "win_payout": -1}],
    )

    status = collect_race_results(_args(tmp_path))

    errors = (tmp_path / "reports" / "result_errors.jsonl").read_text(encoding="utf-8")
    assert status["passed"] is False
    assert "invalid_win_payout" in errors
    assert not (tmp_path / "data" / "race_results.csv").exists()
