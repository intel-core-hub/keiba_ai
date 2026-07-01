from __future__ import annotations

import csv
from pathlib import Path

from scripts.check_approved_exports_ready import check_approved_exports_ready


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_check_approved_exports_ready_reports_missing_files(tmp_path):
    report = check_approved_exports_ready(tmp_path)

    assert report["passed"] is False
    assert report["ready_for_import"] is False
    assert any("schedule.csv" in error for error in report["errors"])


def test_check_approved_exports_ready_accepts_complete_headers_and_rows(tmp_path):
    _write_csv(
        tmp_path / "schedule.csv",
        [
            {
                "race_id": "R1",
                "race_start_at_utc": "2026-06-18T03:00:00+00:00",
                "venue": "TOKYO",
                "race_number": "01",
                "source": "jvlink_export",
            }
        ],
    )
    _write_csv(
        tmp_path / "odds.csv",
        [
            {
                "race_id": "R1",
                "horse_id": "H01",
                "odds": "3.4",
                "snapshot_at_utc": "2026-06-18T02:55:00+00:00",
                "source": "jvlink_export",
            }
        ],
    )
    _write_csv(
        tmp_path / "results.csv",
        [
            {
                "race_id": "R1",
                "horse_id": "H01",
                "finish_position": "1",
                "is_win": "true",
                "win_payout": "340",
                "result_time_utc": "2026-06-18T03:30:00+00:00",
                "source": "jvlink_export",
            }
        ],
    )

    report = check_approved_exports_ready(tmp_path)

    assert report["passed"] is True
    assert report["ready_for_import"] is True
    assert report["errors"] == []


def test_check_approved_exports_ready_rejects_banned_source(tmp_path):
    _write_csv(
        tmp_path / "schedule.csv",
        [{"race_id": "R1", "race_start_at_utc": "2026-06-18T03:00:00+00:00", "source": "mock"}],
    )
    _write_csv(
        tmp_path / "odds.csv",
        [{"race_id": "R1", "horse_id": "H01", "odds": "3.4", "snapshot_at_utc": "2026-06-18T02:55:00+00:00"}],
    )
    _write_csv(
        tmp_path / "results.csv",
        [
            {
                "race_id": "R1",
                "horse_id": "H01",
                "finish_position": "1",
                "is_win": "true",
                "win_payout": "340",
                "result_time_utc": "2026-06-18T03:30:00+00:00",
            }
        ],
    )

    report = check_approved_exports_ready(tmp_path)

    assert report["passed"] is False
    assert any("invalid source" in error for error in report["errors"])
