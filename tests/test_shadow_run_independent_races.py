from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.shadow_run_from_file import run_shadow_file


def _features(rank: int) -> str:
    return json.dumps(
        {
            "favorite_rank": rank,
            "field_size": 10,
            "market_support": 0.08,
            "rank_score": 0.55,
            "recent_form_score": 0.55,
            "consistency_index": 0.5,
        }
    )


def _write_many_race_input(path: Path, races: int) -> None:
    """Many races of all-miss longshot candidates to trigger streak decay."""
    rows = []
    for i in range(races):
        race_id = f"R_INDEP_{i:02d}"
        for sel, odds in (("1", "15.0"), ("2", "13.0")):
            rows.append(
                {
                    "race_id": race_id,
                    "selection": sel,
                    "horse_id": sel,
                    "odds": odds,
                    "hit": "0",
                    "features": _features(4 if sel == "1" else 5),
                    "odds_snapshot_hash": f"{race_id}:{sel}:odds",
                    "feature_snapshot_hash": f"{race_id}:{sel}:features",
                }
            )
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _submitted_races(csv_path: Path) -> set[str]:
    with csv_path.open(encoding="utf-8") as fh:
        return {row["race_id"] for row in csv.DictReader(fh)}


def test_independent_races_evaluates_races_sequential_mode_truncates(tmp_path):
    input_path = tmp_path / "input.csv"
    _write_many_race_input(input_path, races=12)

    seq = run_shadow_file(
        input_path,
        tmp_path / "seq_dec.jsonl",
        tmp_path / "seq_bets.csv",
        settle=True,
    )
    indep = run_shadow_file(
        input_path,
        tmp_path / "ind_dec.jsonl",
        tmp_path / "ind_bets.csv",
        settle=True,
        independent_races=True,
    )

    assert indep["independent_races"] is True
    # per-race state reset must never yield fewer evaluated races than the
    # sequential run, and with an all-miss streak it must yield strictly more
    seq_races = _submitted_races(tmp_path / "seq_bets.csv")
    ind_races = _submitted_races(tmp_path / "ind_bets.csv")
    assert seq_races <= ind_races
    assert len(ind_races) > len(seq_races), (
        f"independent mode should outlast streak decay: "
        f"sequential={sorted(seq_races)}, independent={sorted(ind_races)}"
    )
    # every race gets candidates in independent mode since state never carries
    assert len(ind_races) == 12


def test_bankroll_override_is_reported(tmp_path):
    input_path = tmp_path / "input.csv"
    _write_many_race_input(input_path, races=1)
    report = run_shadow_file(
        input_path,
        tmp_path / "dec.jsonl",
        tmp_path / "bets.csv",
        settle=True,
        bankroll=100000,
    )
    assert report["bankroll_override"] == 100000
    rows = list(csv.DictReader((tmp_path / "bets.csv").open(encoding="utf-8")))
    assert rows and float(rows[0]["bankroll"]) == 100000
