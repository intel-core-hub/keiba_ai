from typing import Any, Dict

class RegimeAwareRiskManager:
    """Simple wrapper that exposes regime-aware exposure and edge rules.

    It is intentionally small: accepts a `regime` string and returns multipliers
    and decisions (no_bet / raise_min_edge).

    Integrate by calling `get_exposure_multiplier(regime)` and applying to
    bet sizing, or `should_bet(regime, edge, uncertainty)` to gate bets.
    """

    DEFAULTS = {
        "stable_market": {"multiplier": 1.0, "min_edge_add": 0.0, "no_bet": False},
        "favorite-heavy": {"multiplier": 0.0, "min_edge_add": 0.03, "no_bet": True},
        "chaotic": {"multiplier": 0.3, "min_edge_add": 0.02, "no_bet": False},
        "high_variance": {"multiplier": 0.5, "min_edge_add": 0.015, "no_bet": False},
        "low_liquidity": {"multiplier": 0.2, "min_edge_add": 0.03, "no_bet": False},
        "distorted_market": {"multiplier": 0.25, "min_edge_add": 0.03, "no_bet": False},
        "uncertainty_spike": {"multiplier": 0.0, "min_edge_add": 0.05, "no_bet": True},
        "calibration_collapse": {"multiplier": 0.35, "min_edge_add": 0.03, "no_bet": False},
        "uncertainty_storm": {"multiplier": 0.0, "min_edge_add": 0.05, "no_bet": True},
        "market_efficiency_spike": {"multiplier": 0.55, "min_edge_add": 0.03, "no_bet": False},
        "unstable_liquidity": {"multiplier": 0.25, "min_edge_add": 0.04, "no_bet": False},
        "favorite_distortion": {"multiplier": 0.15, "min_edge_add": 0.03, "no_bet": True},
        "edge_deterioration": {"multiplier": 0.4, "min_edge_add": 0.025, "no_bet": False},
        "high_payout_volatility": {"multiplier": 0.35, "min_edge_add": 0.02, "no_bet": False},
    }

    def __init__(self, base_min_edge: float = 0.01, overrides: Dict[str, Dict[str, Any]] = None):
        self.base_min_edge = base_min_edge
        self.overrides = dict(self.DEFAULTS)
        if overrides:
            self.overrides.update(overrides)

    def get_policy(self, regime: str) -> Dict[str, Any]:
        return self.overrides.get(regime, self.overrides.get("stable_market"))

    def get_exposure_multiplier(self, regime: str) -> float:
        return float(self.get_policy(regime)["multiplier"])

    def get_min_edge(self, regime: str) -> float:
        return float(self.base_min_edge + self.get_policy(regime)["min_edge_add"])

    def should_bet(self, regime: str, edge: float, uncertainty: float = 0.0) -> bool:
        p = self.get_policy(regime)
        if p.get("no_bet", False):
            return False
        min_edge = self.get_min_edge(regime)
        # optionally factor uncertainty into gating
        if uncertainty > 0.5:
            # conservative: require larger edge under high uncertainty
            min_edge = max(min_edge, min_edge * (1.0 + uncertainty))
        return edge >= min_edge
