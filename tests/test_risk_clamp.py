from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.decision_engine import DecisionEngine
from core.betting.risk_clamp import RiskClamp, RiskClampInput, VALID_NO_BET_REASONS
from core.low_latency_execution import LowLatencyExecutionEngine


def _valid_input(**overrides):
    data = {
        "odds_snapshot": {"present": True},
        "feature_snapshot": {"present": True},
        "calibration_state": {"expired": False, "invalid": False},
        "bankroll_snapshot": {"bankroll": 100000.0, "drawdown": 0.0},
        "race_state": {"race_cancelled": False},
        "clock_state": {"clock_skew_ms": 0},
        "model_state": {"expected_hash": "model-a", "active_hash": "model-a"},
        "policy_snapshot": {
            "expected_hash": "policy-a",
            "active_hash": "policy-a",
            "max_odds_age_ms": 2000,
            "max_feature_age_ms": 5000,
            "max_clock_skew_ms": 500,
        },
        "sizing_proposal": {
            "allowed": True,
            "max_stake": 100.0,
            "risk_multiplier": 0.8,
            "reason": "OK",
        },
        "odds_freshness_ms": 100.0,
        "feature_age_ms": 100.0,
    }
    data.update(overrides)
    return RiskClampInput(**data)


def test_risk_clamp_allows_valid_positive_proposal_deterministically():
    clamp = RiskClamp()
    first = clamp.evaluate(_valid_input())
    second = clamp.evaluate(_valid_input())

    assert first.allowed is True
    assert first.decision == "BET"
    assert first.max_stake == 100.0
    assert first.risk_multiplier == 0.8
    assert first.risk_limits_hash == second.risk_limits_hash


def test_risk_clamp_rejects_missing_and_stale_odds():
    clamp = RiskClamp()

    missing = clamp.evaluate(_valid_input(odds_snapshot={"missing": True}))
    stale = clamp.evaluate(_valid_input(odds_freshness_ms=3000.0))

    assert missing.decision == "NO_BET"
    assert missing.reason == "missing_odds"
    assert stale.reason == "stale_odds"


def test_risk_clamp_rejects_missing_and_stale_features():
    clamp = RiskClamp()

    missing = clamp.evaluate(_valid_input(feature_snapshot={"missing": True}))
    stale = clamp.evaluate(_valid_input(feature_age_ms=6000.0))

    assert missing.reason == "missing_features"
    assert stale.reason == "stale_features"


def test_risk_clamp_rejects_calibration_and_bankroll_failures():
    clamp = RiskClamp()

    assert clamp.evaluate(_valid_input(calibration_state={"expired": True})).reason == "calibration_expired"
    assert clamp.evaluate(_valid_input(calibration_state={"invalid": True})).reason == "calibration_invalid"
    assert clamp.evaluate(_valid_input(bankroll_snapshot={"uncertain": True})).reason == "bankroll_uncertain"
    assert clamp.evaluate(_valid_input(bankroll_snapshot={"stale": True})).reason == "bankroll_stale"


def test_risk_clamp_rejects_clock_race_model_and_policy_failures():
    clamp = RiskClamp()

    assert clamp.evaluate(_valid_input(clock_state={"clock_skew_ms": 900})).reason == "clock_skew"
    assert clamp.evaluate(_valid_input(race_state={"race_cancelled": True})).reason == "race_cancelled"
    assert clamp.evaluate(_valid_input(model_state={"expected_hash": "a", "active_hash": "b"})).reason == "model_hash_mismatch"
    assert clamp.evaluate(_valid_input(policy_snapshot={"expected_hash": "a", "active_hash": "b"})).reason == "policy_hash_mismatch"


def test_risk_clamp_preserves_operational_no_bet_reasons():
    clamp = RiskClamp()
    reasons = {
        "session_expired",
        "ip_blocked",
        "retry_budget_exceeded",
        "odds_spike",
        "audit_enqueue_failed",
        "prediction_timeout",
        "execution_timeout",
    }

    assert reasons.issubset(VALID_NO_BET_REASONS)
    for reason in reasons:
        result = clamp.evaluate(_valid_input(sizing_proposal={"allowed": False, "reason": reason}))
        assert result.reason == reason


def test_risk_clamp_normalizes_operational_failure_aliases():
    clamp = RiskClamp()

    assert clamp.evaluate(_valid_input(sizing_proposal={"allowed": False, "reason": "CONSECUTIVE_TIMEOUTS"})).reason == "retry_budget_exceeded"
    assert clamp.evaluate(_valid_input(sizing_proposal={"allowed": False, "reason": "retry budget"})).reason == "retry_budget_exceeded"
    assert clamp.evaluate(_valid_input(sizing_proposal={"allowed": False, "reason": "unauthorized"})).reason == "session_expired"
    assert clamp.evaluate(_valid_input(sizing_proposal={"allowed": False, "reason": "IP blocked"})).reason == "ip_blocked"
    assert clamp.evaluate(_valid_input(sizing_proposal={"allowed": False, "reason": "audit enqueue failed"})).reason == "audit_enqueue_failed"
    assert clamp.evaluate(_valid_input(sizing_proposal={"allowed": False, "reason": "surprise failure"})).reason == "unknown_fail_closed"


class _Predictor:
    model_hash = "model-a"

    def predict(self, *args, **kwargs):
        return 0.8


class _BetSizer:
    def calculate_bet(self, **kwargs):
        return 100


class _RiskManager:
    bankroll = 100000.0

    def __init__(self, can_bet=True):
        self._can_bet = can_bet
        self.registered = 0.0

    def update_uncertainty_state(self, **kwargs):
        return self.status()

    def status(self):
        return {"bankroll": self.bankroll, "drawdown": 0.0}

    def drawdown(self):
        return 0.0

    def can_bet(self):
        return self._can_bet

    def risk_multiplier(self):
        return 1.0

    def max_bet_size(self):
        return 100.0

    def register_bet(self, size):
        self.registered += float(size)


def test_decision_engine_requires_risk_clamp_permission():
    deny = RiskClamp()
    risk = _RiskManager(can_bet=False)
    engine = DecisionEngine(
        predictor=_Predictor(),
        bet_sizer=_BetSizer(),
        risk_manager=risk,
        calibrator=type("C", (), {"calibrate": lambda self, p: p})(),
        risk_clamp=deny,
    )

    result = engine.evaluate_candidate("R1", {"selection": "H1", "odds": 5.0, "features": {"x": 1}})

    assert result is None
    assert risk.registered == 0.0


class _SizingRisk:
    def __init__(self, proposal):
        self.proposal = proposal

    def calculate_sizing(self, *args, **kwargs):
        return self.proposal


class _RawPredictor:
    model_hash = "model-a"

    def predict(self, *args, **kwargs):
        return 0.8


class _IPAT:
    def __init__(self):
        self.placed = False

    async def fetch_live_odds_async(self, race_id):
        return {
            "timestamp": time.time(),
            "odds": [5.0],
            "precomputed_feature_vector": [{"rank_score": 0.8}],
            "calibration_state": {"expired": False, "invalid": False},
            "bankroll_state": {"uncertain": False, "stale": False},
        }

    async def place_bet_async(self, race_id, allocations):
        self.placed = True
        return {"status": "submitted"}


def test_low_latency_engine_requires_risk_clamp_permission_for_proposal():
    ipat = _IPAT()
    engine = LowLatencyExecutionEngine(
        predictor=_RawPredictor(),
        risk_manager=_SizingRisk({"should_bet": True, "allocations": []}),
        ipat_client=ipat,
        staleness_threshold=1.0,
    )

    result = asyncio.run(engine.execute_critical_path("R1", timeout_sec=0.2))

    assert result["decision"] == "NO_BET"
    assert result["reason"] == "risk_limits_invalid"
    assert ipat.placed is False
