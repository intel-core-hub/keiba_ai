from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class RegimeAction:
    regime: str
    mode: str
    exposure_multiplier: float
    min_edge_add: float
    no_bet: bool
    reason: str


class RegimeExposureController:
    """Explainable mapping from regime labels to survival actions."""

    def __init__(self, base_min_edge: float = 0.01, defensive_exposure: float = 0.45, normal_exposure: float = 1.0):
        self.base_min_edge = float(base_min_edge)
        self.defensive_exposure = float(defensive_exposure)
        self.normal_exposure = float(normal_exposure)

    def normal_mode(self, regime: str = "stable_market") -> RegimeAction:
        return RegimeAction(regime=regime, mode="NORMAL", exposure_multiplier=self.normal_exposure, min_edge_add=0.0, no_bet=False, reason="stable regime")

    def defensive_mode(self, regime: str = "calibration_collapse") -> RegimeAction:
        return RegimeAction(regime=regime, mode="DEFENSIVE", exposure_multiplier=self.defensive_exposure, min_edge_add=0.02, no_bet=False, reason="market quality degraded")

    def no_bet(self, regime: str = "uncertainty_storm") -> RegimeAction:
        return RegimeAction(regime=regime, mode="HALT", exposure_multiplier=0.0, min_edge_add=0.05, no_bet=True, reason="risk off")

    def increase_edge_threshold(self, regime: str = "market_efficiency_spike") -> RegimeAction:
        return RegimeAction(regime=regime, mode="EDGE_TIGHTEN", exposure_multiplier=0.6, min_edge_add=0.03, no_bet=False, reason="market edge compressed")

    def action_for_regime(self, regime: str) -> RegimeAction:
        normalized = str(regime or "stable_market").lower()
        if normalized in {"calibration_collapse", "collapse", "drift"}:
            return self.defensive_mode(regime=regime)
        if normalized in {"uncertainty_storm", "uncertainty_spike"}:
            return self.no_bet(regime=regime)
        if normalized in {"market_efficiency_spike", "market_efficiency"}:
            return self.increase_edge_threshold(regime=regime)
        if normalized in {"unstable_liquidity", "high_payout_volatility", "favorite_distortion", "edge_deterioration"}:
            return self.defensive_mode(regime=regime)
        return self.normal_mode(regime=regime)

    def policy(self, regime: str) -> Dict[str, object]:
        action = self.action_for_regime(regime)
        return {
            "regime": action.regime,
            "mode": action.mode,
            "exposure_multiplier": action.exposure_multiplier,
            "min_edge": self.base_min_edge + action.min_edge_add,
            "no_bet": action.no_bet,
            "reason": action.reason,
        }
