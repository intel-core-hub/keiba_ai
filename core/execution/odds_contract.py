"""Canonical definitions for odds and expected-value fields in bets.csv.

predicted_odds
    Market odds at decision time (pre-bet quote). Used as the basis for
    EdgeCalculator EV and stake sizing. NOT model-implied fair odds.

confirmed_odds
    Odds at execution / fill time (from API or shadow odds fetcher).

expected_value
    Pre-bet EV: adjusted_prob * predicted_odds - 1 (from EdgeCalculator when
    available, else probability * predicted_odds - 1).

expected_value_per_unit
    Post-fill EV: probability * confirmed_odds - 1. Reflects slippage impact.
"""

from __future__ import annotations

from typing import Any, Optional


def market_odds_at_decision(decision: Any) -> float:
    """Return the market odds used when the bet decision was made."""
    return float(getattr(decision, "odds", 0.0) or 0.0)


def decision_probability(decision: Any) -> float:
    """Probability used for EV (calibrated when present)."""
    calibrated = getattr(decision, "calibrated_probability", None)
    if calibrated is not None:
        try:
            return float(calibrated)
        except (TypeError, ValueError):
            pass
    return float(getattr(decision, "probability", 0.0) or 0.0)


def pre_bet_expected_value(decision: Any) -> float:
    """Pre-bet EV from EdgeCalculator when available, else prob * odds - 1."""
    ev = getattr(decision, "expected_value", None)
    if ev is not None:
        try:
            return float(ev)
        except (TypeError, ValueError):
            pass
    odds = market_odds_at_decision(decision)
    prob = decision_probability(decision)
    if odds <= 1.0:
        return -1.0
    return prob * odds - 1.0


def fill_expected_value(probability: float, confirmed_odds: float) -> float:
    """Post-fill EV per unit stake."""
    if confirmed_odds <= 1.0:
        return -1.0
    return float(probability) * float(confirmed_odds) - 1.0


def slippage_pct(predicted_odds: float, confirmed_odds: float) -> float:
    if predicted_odds <= 0:
        return 0.0
    return (float(confirmed_odds) - float(predicted_odds)) / float(predicted_odds)
