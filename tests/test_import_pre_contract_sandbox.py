from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.import_pre_contract_sandbox import import_pre_contract_sandbox


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
        [
            {
                "race_id": "R1",
                "race_start_at_utc": "2026-06-18T03:00:00+00:00",
                "venue": "TOKYO",
                "race_number": "01",
                "source": "pre_contract_sandbox",
            }
        ],
    )
    _write_csv(
        odds,
        [
            {
                "race_id": "R1",
                "horse_id": "H01",
                "odds": "3.4",
                "snapshot_at_utc": "2026-06-18T02:55:00+00:00",
                "source": "pre_contract_sandbox",
            },
            {
                "race_id": "R1",
                "horse_id": "H02",
                "odds": "7.8",
                "snapshot_at_utc": "2026-06-18T02:55:00+00:00",
                "source": "pre_contract_sandbox",
            },
        ],
    )
    _write_csv(
        results,
        [
            {
                "race_id": "R1",
                "horse_id": "H01",
                "finish_position": "1",
                "is_win": "true",
                "win_payout": "340",
                "result_time_utc": "2026-06-18T03:30:00+00:00",
                "source": "pre_contract_sandbox",
            },
            {
                "race_id": "R1",
                "horse_id": "H02",
                "finish_position": "2",
                "is_win": "false",
                "win_payout": "0",
                "result_time_utc": "2026-06-18T03:30:00+00:00",
                "source": "pre_contract_sandbox",
            },
        ],
    )
    return schedule, odds, results


def test_import_pre_contract_sandbox_writes_non_evidence_live_layout(tmp_path):
    schedule, odds, results = _valid_inputs(tmp_path)

    report = import_pre_contract_sandbox(
        schedule_input=schedule,
        odds_input=odds,
        results_input=results,
        output_root=tmp_path / "sandbox_live_inputs",
        source="pre_contract_sandbox",
        clean=True,
        min_races=1,
        min_horses_per_race=2,
    )

    schedule_out = json.loads((tmp_path / "sandbox_live_inputs" / "today_races.json").read_text(encoding="utf-8"))
    odds_out = json.loads((tmp_path / "sandbox_live_inputs" / "odds" / "R1.json").read_text(encoding="utf-8"))

    assert report["passed"] is True
    assert report["evidence_eligible"] is False
    assert schedule_out[0]["source"] == "pre_contract_sandbox"
    assert odds_out[0]["source"] == "pre_contract_sandbox"


def test_import_pre_contract_sandbox_rejects_approved_source_label(tmp_path):
    schedule, odds, results = _valid_inputs(tmp_path)

    with pytest.raises(ValueError, match="reserved for approved real-data"):
        import_pre_contract_sandbox(
            schedule_input=schedule,
            odds_input=odds,
            results_input=results,
            output_root=tmp_path / "sandbox_live_inputs",
            source="jvlink_export",
        )


def test_import_pre_contract_sandbox_rejects_canonical_output(tmp_path, monkeypatch):
    schedule, odds, results = _valid_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="may not write under data/live_inputs"):
        import_pre_contract_sandbox(
            schedule_input=schedule,
            odds_input=odds,
            results_input=results,
            output_root=Path("data/live_inputs"),
            source="pre_contract_sandbox",
        )
