from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.build_pre_contract_shadow_input import build_pre_contract_shadow_input


def test_build_pre_contract_shadow_input_writes_hit_and_features(tmp_path):
    live = tmp_path / "live_inputs"
    (live / "odds").mkdir(parents=True)
    (live / "results").mkdir(parents=True)
    (live / "today_races.json").write_text(
        json.dumps([{"race_id": "R1", "race_start_at_utc": "2026-06-18T03:00:00+00:00"}]),
        encoding="utf-8",
    )
    (live / "odds" / "R1.json").write_text(
        json.dumps(
            [
                {"race_id": "R1", "horse_id": "H01", "odds": 3.4},
                {"race_id": "R1", "horse_id": "H02", "odds": 7.8},
            ]
        ),
        encoding="utf-8",
    )
    (live / "results" / "R1.json").write_text(
        json.dumps(
            [
                {"race_id": "R1", "horse_id": "H01", "is_win": True},
                {"race_id": "R1", "horse_id": "H02", "is_win": False},
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "shadow_input.csv"

    report = build_pre_contract_shadow_input(
        schedule=live / "today_races.json",
        odds_dir=live / "odds",
        results_dir=live / "results",
        output=output,
    )

    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    features = json.loads(rows[0]["features"])
    assert report["passed"] is True
    assert report["evidence_eligible"] is False
    assert report["row_count"] == 2
    assert rows[0]["hit"] == "1"
    assert features["field_size"] == 2
