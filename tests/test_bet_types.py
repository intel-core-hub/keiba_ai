from __future__ import annotations

import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.bet_types import (
    BetCandidate,
    BetTypeConfig,
    BetTypeRegistry,
    apply_fraction_multiplier,
    assert_execution_allowed,
    default_registry,
    evaluate_hit,
    filter_execution_candidates,
    is_disabled_bet_type,
    is_production_eligible,
    is_shadow_only,
    load_bet_type_config,
    make_settlement,
    normalize_bet_type,
    normalize_legacy_win_record,
    normalize_legs,
    parse_legs,
    settle_bet,
    validate_bet_type_exposure,
    validate_bet_candidate,
)


def test_normalize_supported_bet_types_and_aliases():
    assert normalize_bet_type("win") == "win"
    assert normalize_bet_type("place") == "place"
    assert normalize_bet_type("wide") == "wide"
    assert normalize_bet_type("quinella") == "quinella"
    assert normalize_bet_type("trio") == "trio"
    assert normalize_bet_type("exacta") == "exacta"
    assert normalize_bet_type("trifecta") == "trifecta"
    assert normalize_bet_type("単勝") == "win"
    assert normalize_bet_type("馬連") == "quinella"
    assert normalize_bet_type("wakuren") == "wakuren"
    assert normalize_bet_type("枠連") == "wakuren"
    assert normalize_bet_type("bracket_quinella") == "wakuren"


def test_normalize_legs_honors_ordering():
    assert normalize_legs("wide", ["H05", "H01"]) == ("H01", "H05")
    assert normalize_legs("quinella", ["H05", "H01"]) == ("H01", "H05")
    assert normalize_legs("exacta", ["H05", "H01"]) == ("H05", "H01")
    assert normalize_legs("trifecta", ["H03", "H01", "H02"]) == ("H03", "H01", "H02")


def test_validate_rejects_duplicate_legs_disabled_and_bad_money():
    registry = default_registry()
    duplicate = BetCandidate(
        race_id="R1",
        bet_type="wide",
        legs=("H01", "H01"),
        ordered=False,
        odds=8.4,
        stake=100,
        shadow_only=False,
        production_candidate=True,
        source="test",
        metadata={},
    )
    with pytest.raises(ValueError, match="duplicate"):
        validate_bet_candidate(duplicate, registry.get("wide"), field_size=16)

    with pytest.raises(ValueError, match="disabled"):
        BetCandidate.from_mapping(
            {"race_id": "R1", "bet_type": "exacta", "legs": ["H01", "H02"], "odds": 12, "stake": 100}
        )

    with pytest.raises(ValueError, match="odds"):
        BetCandidate.from_mapping({"race_id": "R1", "horse_id": "H01", "odds": 0, "stake": 100})

    with pytest.raises(ValueError, match="stake"):
        BetCandidate.from_mapping({"race_id": "R1", "horse_id": "H01", "odds": 3.0, "stake": -1})


def test_modes_are_classified_correctly():
    assert is_production_eligible("win")
    assert is_production_eligible("place")
    assert is_production_eligible("wide")
    assert is_shadow_only("quinella")
    assert is_shadow_only("trio")
    assert is_shadow_only("wakuren")
    assert is_disabled_bet_type("exacta")
    assert is_disabled_bet_type("trifecta")


def test_hit_rules_for_supported_and_ordered_bet_types():
    finish = {"H01": 1, "H02": 2, "H03": 3, "H04": 4}
    assert evaluate_hit("win", ["H01"], finish)
    assert not evaluate_hit("win", ["H02"], finish)
    assert evaluate_hit("place", ["H03"], finish)
    assert not evaluate_hit("place", ["H04"], finish)
    assert evaluate_hit("wide", ["H03", "H01"], finish)
    assert not evaluate_hit("wide", ["H04", "H01"], finish)
    assert evaluate_hit("quinella", ["H02", "H01"], finish)
    assert not evaluate_hit("quinella", ["H03", "H01"], finish)
    assert evaluate_hit("trio", ["H03", "H01", "H02"], finish)
    assert evaluate_hit("exacta", ["H01", "H02"], finish)
    assert not evaluate_hit("exacta", ["H02", "H01"], finish)
    assert evaluate_hit("trifecta", ["H01", "H02", "H03"], finish)


def test_wakuren_hit_requires_bracket_mapping_and_matches_top_two():
    finish = {"H01": 1, "H02": 2, "H03": 3, "H04": 4}
    brackets = {"H01": 3, "H02": 7, "H03": 3, "H04": 1}
    assert evaluate_hit("wakuren", ["3", "7"], finish, brackets=brackets)
    assert evaluate_hit("wakuren", ["7", "3"], finish, brackets=brackets)
    assert not evaluate_hit("wakuren", ["1", "3"], finish, brackets=brackets)
    # missing mapping must fail closed, never silently miss
    with pytest.raises(ValueError, match="bracket"):
        evaluate_hit("wakuren", ["3", "7"], finish)
    # horse missing from the bracket mapping is a miss, not a crash
    assert not evaluate_hit("wakuren", ["3", "7"], finish, brackets={"H01": 3})


def test_wakuren_candidate_validates_bracket_leg_range():
    candidate = BetCandidate.from_mapping(
        {
            "race_id": "R1",
            "bet_type": "枠連",
            "legs": ["7", "3"],
            "odds": 14.2,
            "stake": 100,
            "field_size": 16,
        }
    )
    assert candidate.bet_type == "wakuren"
    assert candidate.legs == ("3", "7")
    assert candidate.shadow_only is True

    with pytest.raises(ValueError, match="bracket numbers"):
        BetCandidate.from_mapping(
            {"race_id": "R1", "bet_type": "wakuren", "legs": ["3", "9"], "odds": 14.2, "stake": 100}
        )
    with pytest.raises(ValueError, match="shadow_only"):
        assert_execution_allowed("wakuren")


def test_settle_bet_profit_and_legacy_win_conversion():
    assert settle_bet(100, 360, True) == 260
    assert settle_bet(500, hit=True, payout_per_100=360) == 1300
    assert settle_bet(500, hit=True, gross_payout=1800) == 1300
    assert settle_bet(100, 0, False) == -100
    with pytest.raises(ValueError, match="payout"):
        settle_bet(100, 0, True)

    row = normalize_legacy_win_record({"race_id": "R1", "horse_id": "H01", "odds": 3.6, "win_payout": 360})
    assert row["bet_type"] == "win"
    assert row["legs"] == ["H01"]
    assert row["ordered"] is False
    assert row["shadow_only"] is False
    assert row["production_candidate"] is True
    assert row["payout_per_100"] == 360
    assert row["payout"] == 360


def test_settlement_rejects_ambiguous_or_bad_payouts():
    with pytest.raises(ValueError, match="exactly one payout"):
        settle_bet(100, hit=True)
    with pytest.raises(ValueError, match="exactly one payout"):
        settle_bet(100, 360, True, payout_per_100=360)
    with pytest.raises(ValueError, match="payout_per_100"):
        settle_bet(100, hit=True, payout_per_100=0)
    with pytest.raises(ValueError, match="stake"):
        settle_bet(-100, 360, True)

    settled = make_settlement(
        race_id="R1",
        bet_type="win",
        legs=["H01"],
        stake=500,
        hit=True,
        payout_per_100=360,
    )
    assert settled.payout == 1800
    assert settled.gross_payout == 1800
    assert settled.profit == 1300


def test_registry_config_validation_and_parsing_errors(tmp_path):
    assert BetTypeConfig("custom", True, False, False, False, 1).mode.value == "disabled"
    registry = default_registry()
    with pytest.raises(ValueError, match="unknown"):
        registry.get("not-a-bet")
    with pytest.raises(ValueError, match="unknown"):
        normalize_bet_type("not-a-bet")
    with pytest.raises(ValueError, match="selection"):
        normalize_legacy_win_record({"race_id": "R1"})
    with pytest.raises(ValueError, match="legs missing"):
        normalize_legacy_win_record({"race_id": "R1", "bet_type": "wide"})
    assert parse_legs("") == []
    assert parse_legs("H02|H01") == ["H02", "H01"]
    assert parse_legs('{"horse":"H01"}') == ['{"horse":"H01"}']

    bad_config = tmp_path / "bad.yaml"
    bad_config.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bet_types mapping"):
        load_bet_type_config(bad_config)

    bad_config.write_text("bet_types:\n  win: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_bet_type_config(bad_config)

    bad_config.write_text("bet_types:\n  win:\n    enabled: true\n    legs: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required"):
        load_bet_type_config(bad_config)


def test_exposure_clamp_filter_and_execution_guards():
    registry = default_registry()
    win_a = BetCandidate.from_mapping({"race_id": "R1", "horse_id": "H01", "odds": 3.0, "stake": 800})
    win_b = BetCandidate.from_mapping({"race_id": "R1", "horse_id": "H02", "odds": 4.0, "stake": 100})
    accepted, rejected = validate_bet_type_exposure([win_a, win_b], bankroll=1000, registry=registry)
    assert accepted[0].stake == 500
    assert accepted[0].metadata["risk_clamped"] is True
    assert rejected[0]["reason"] == "max_combinations_per_race_exceeded"

    too_large = BetCandidate.from_mapping({"race_id": "R2", "horse_id": "H01", "odds": 3.0, "stake": 800})
    accepted, rejected = validate_bet_type_exposure([too_large], bankroll=1000, registry=registry, clamp=False)
    assert accepted == []
    assert rejected[0]["reason"] == "max_race_exposure_share_exceeded"

    assert apply_fraction_multiplier(1000, "place") == 750
    assert_execution_allowed("win")
    with pytest.raises(ValueError, match="shadow_only"):
        assert_execution_allowed("quinella")
    with pytest.raises(ValueError, match="disabled"):
        assert_execution_allowed("exacta")

    accepted, rejected = filter_execution_candidates(
        [
            {"race_id": "R3", "horse_id": "H01", "odds": 3.0, "stake": 100},
            {"race_id": "R3", "bet_type": "quinella", "legs": ["H01", "H02"], "odds": 8.0, "stake": 100},
        ],
        registry=registry,
    )
    assert len(accepted) == 1
    assert len(rejected) == 1
