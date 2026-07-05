from __future__ import annotations

import csv
from pathlib import Path

from scripts.evaluate_pre_contract_sandbox import evaluate_pre_contract_sandbox


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_evaluate_pre_contract_sandbox_outputs_json_and_markdown(tmp_path):
    shadow = tmp_path / "shadow_input.csv"
    bets = tmp_path / "bets.csv"
    _write_csv(
        shadow,
        [
            {
                "race_id": "R1",
                "selection": "H01",
                "horse_id": "H01",
                "odds": "3.4",
                "hit": "1",
                "features": '{"favorite_rank":1,"field_size":2}',
            },
            {
                "race_id": "R1",
                "selection": "H02",
                "horse_id": "H02",
                "odds": "21.0",
                "hit": "0",
                "features": '{"favorite_rank":2,"field_size":2}',
            },
        ],
    )
    _write_csv(
        bets,
        [
            {"race_id": "R1", "selection": "H01", "odds": "3.4", "stake": "100", "profit": "240", "hit": "1", "api_status": "shadow"},
            {"race_id": "R1", "selection": "H02", "odds": "21.0", "stake": "100", "profit": "-100", "hit": "0", "api_status": "shadow"},
        ],
    )

    report = evaluate_pre_contract_sandbox(
        bets_csv=bets,
        shadow_input_csv=shadow,
        output_json=tmp_path / "eval.json",
        output_md=tmp_path / "eval.md",
    )

    assert report["evidence_eligible"] is False
    assert report["candidate_count"] == 2
    assert report["profit_sum"] == 140
    assert report["odds_regime"]["FAVORITE_TO_BALANCED"]["bets"] == 1
    assert report["odds_regime"]["DEEP_LONGSHOT"]["bets"] == 1
    assert (tmp_path / "eval.md").exists()
