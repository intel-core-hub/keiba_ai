from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_import_jvlink_exports_cli_uses_jvlink_source(tmp_path):
    schedule = tmp_path / "schedule.csv"
    odds = tmp_path / "odds.csv"
    results = tmp_path / "results.csv"
    output = tmp_path / "live_inputs"
    _write_csv(
        schedule,
        [{"race_id": "R1", "race_start_at_utc": "2026-06-02T03:00:00+00:00"}],
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

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.import_jvlink_exports",
            "--schedule-input",
            str(schedule),
            "--odds-input",
            str(odds),
            "--results-input",
            str(results),
            "--output-root",
            str(output),
            "--min-races",
            "1",
            "--min-horses-per-race",
            "2",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    odds_out = json.loads((output / "odds" / "R1.json").read_text(encoding="utf-8"))
    assert report["source"] == "jvlink_export"
    assert odds_out[0]["source"] == "jvlink_export"
