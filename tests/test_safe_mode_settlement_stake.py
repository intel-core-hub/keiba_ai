from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.shadow_run_from_file import run_shadow_file


def _write_shadow_input(path: Path) -> None:
    rows = [
        # winner at odds 10.0 and one loser, both strong-edge longshots so the
        # engine produces candidates
        {
            "race_id": "R_SAFE_STAKE",
            "selection": "1",
            "horse_id": "1",
            "odds": "10.0",
            "hit": "1",
            "features": '{"favorite_rank":4,"field_size":10,"market_support":0.1,'
                        '"rank_score":0.6,"recent_form_score":0.6,"consistency_index":0.5}',
            "odds_snapshot_hash": "R_SAFE_STAKE:1:odds",
            "feature_snapshot_hash": "R_SAFE_STAKE:1:features",
        },
        {
            "race_id": "R_SAFE_STAKE",
            "selection": "2",
            "horse_id": "2",
            "odds": "12.0",
            "hit": "0",
            "features": '{"favorite_rank":5,"field_size":10,"market_support":0.08,'
                        '"rank_score":0.55,"recent_form_score":0.55,"consistency_index":0.5}',
            "odds_snapshot_hash": "R_SAFE_STAKE:2:odds",
            "feature_snapshot_hash": "R_SAFE_STAKE:2:features",
        },
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_safe_mode_settles_with_executed_stake(tmp_path):
    """Settlement P&L must use the SAFE_MODE-clamped executed stake.

    Regression: the executor clamped the reported stake to the minimum lot
    while the decision engine settled with the pre-clamp bet_size, so paper
    losses and payouts were overstated relative to the recorded stake.
    """
    shadow_input = tmp_path / "shadow_input.csv"
    _write_shadow_input(shadow_input)

    run_shadow_file(
        shadow_input,
        tmp_path / "decisions.jsonl",
        tmp_path / "bets.csv",
        settle=True,
    )

    rows = list(csv.DictReader((tmp_path / "bets.csv").open(encoding="utf-8")))
    settled = [r for r in rows if r.get("profit") not in ("", None)]
    assert settled, "expected settled candidate rows"
    for row in settled:
        stake = float(row["stake"])
        odds = float(row["odds"])
        profit = float(row["profit"])
        if row["hit"] == "1":
            assert profit == stake * (odds - 1), (
                f"hit profit {profit} != stake*(odds-1) with stake={stake}, odds={odds}"
            )
        else:
            assert profit == -stake, (
                f"miss profit {profit} != -stake with stake={stake}"
            )
