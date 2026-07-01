from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.bet_types import (
    BetCandidate,
    assert_execution_allowed,
    filter_execution_candidates,
    normalize_legacy_win_record,
)
from core.betting.decision_engine import Decision
from core.execution.bet_executor import BetExecutor


class _StubRisk:
    bankroll = 100_000.0

    def status(self):
        return {
            "bankroll": self.bankroll,
            "drawdown": 0.0,
            "risk_multiplier": 1.0,
            "lose_streak": 0,
            "win_streak": 0,
            "race_risk_used": 0.0,
        }


def _decision_with_proof(**overrides):
    decision = Decision(
        race_id="R1",
        selection="H01-H02",
        probability=0.2,
        calibrated_probability=0.18,
        market_probability=0.1,
        odds=8.0,
        edge=0.05,
        expected_value=0.8,
        uncertainty_score=0.1,
        edge_quality=0.7,
        bet_size=500,
        bet_type="quinella",
        legs=("H01", "H02"),
        ordered=False,
        shadow_only=True,
        production_candidate=False,
    )
    decision.risk_limits_hash = "risk-hash"
    decision.risk_clamp_reason = "risk_clamp_allowed"
    decision.risk_clamp_allowed = True
    decision.policy_hash = "policy-hash"
    decision.model_hash = "model-hash"
    decision.odds_snapshot_hash = "odds-hash"
    decision.feature_snapshot_hash = "feature-hash"
    for key, value in overrides.items():
        setattr(decision, key, value)
    return decision


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_shadow_only_can_be_decision_evidence_but_not_execution_candidate():
    normalized = normalize_legacy_win_record(
        {"race_id": "R1", "bet_type": "quinella", "legs": ["H02", "H01"], "odds": 8.0, "stake": 100}
    )
    assert normalized["shadow_only"] is True
    assert normalized["production_candidate"] is False

    accepted, rejected = filter_execution_candidates(
        [{"race_id": "R1", "bet_type": "quinella", "legs": ["H01", "H02"], "odds": 8.0, "stake": 100}]
    )
    assert accepted == []
    assert "shadow_only" in rejected[0]["reason"]


def test_exacta_and_trifecta_are_rejected_at_candidate_generation():
    with pytest.raises(ValueError, match="disabled"):
        BetCandidate.from_mapping({"race_id": "R1", "bet_type": "exacta", "legs": ["H01", "H02"], "odds": 12, "stake": 100})
    with pytest.raises(ValueError, match="disabled"):
        BetCandidate.from_mapping(
            {"race_id": "R1", "bet_type": "trifecta", "legs": ["H01", "H02", "H03"], "odds": 30, "stake": 100}
        )


def test_bet_executor_blocks_shadow_only_before_submit(tmp_path):
    executor = BetExecutor(
        risk_manager=_StubRisk(),
        decision_log_path=str(tmp_path / "decisions.jsonl"),
        csv_report_path=str(tmp_path / "bets.csv"),
        shadow_mode=True,
        safe_mode=True,
    )
    result = executor.execute_bet(_decision_with_proof())
    events = _read_jsonl(tmp_path / "decisions.jsonl")

    assert result["blocked"] is True
    assert result["reason"] == "shadow_only_execution_rejected"
    assert "BetSubmitted" not in [event["event_type"] for event in events]
    assert events[-1]["event_type"] == "BetTypeExecutionRejected"


def test_execution_guard_rejects_production_candidate_false():
    with pytest.raises(ValueError, match="shadow_only"):
        assert_execution_allowed("quinella")
