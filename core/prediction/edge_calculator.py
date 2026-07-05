import numpy as np


class EdgeCalculator:
    """Compute edge and EV using market odds at decision time.

    The ``odds`` argument must be the pre-bet market quote (same as
    ``predicted_odds`` in bets.csv). EV is ``adjusted_prob * odds - 1``.
    """

    def __init__(
        self,
        min_edge=0.02,
        market_trust=0.35,
        regime_trust_map=None,
        max_edge_clip=0.25,
        odds_slip=0.05,
    ):
        self.min_edge = min_edge
        self.market_trust = market_trust
        self.regime_trust_map = dict(regime_trust_map or {
            "NORMAL": 0.25,
            "VOLATILE": 0.10,
            "DRIFT": 0.15,
            "WEAK_EDGE": 0.05,
        })
        self.max_edge_clip = max_edge_clip
        self.odds_slip = odds_slip

    def market_trust_for_regime(self, regime=None):
        if regime is None:
            return float(self.regime_trust_map.get("NORMAL", 0.25))
        return float(self.regime_trust_map.get(str(regime).upper(), 0.25))

    def slippage_margin(self, odds):
        odds = float(odds)
        base_slip = max(float(self.odds_slip), 0.0)
        if odds >= 50.0:
            multiplier = 4.0
        elif odds >= 30.0:
            multiplier = 3.0
        elif odds >= 10.0:
            multiplier = 1.5
        else:
            multiplier = 1.0
        return min(base_slip * multiplier, 0.50)

    def odds_to_prob(self, odds):
        if odds <= 1.0:
            return 0.0
        return 1.0 / odds

    def blend_with_market(self, ai_prob, market_prob, regime=None):
        market_trust = self.market_trust_for_regime(regime)

        return (
            (1 - market_trust) * ai_prob
            + market_trust * market_prob
        )

    def calculate_edge(self, ai_prob, odds, regime=None):

        odds_slip = self.slippage_margin(odds)
        safe_odds = max(float(odds) * (1.0 - odds_slip), 1.0)

        market_prob = self.odds_to_prob(safe_odds)

        adjusted_prob = self.blend_with_market(
            ai_prob,
            market_prob,
            regime=regime,
        )

        edge = adjusted_prob - market_prob

        edge = np.clip(
            edge,
            -self.max_edge_clip,
            self.max_edge_clip,
        )

        ev = adjusted_prob * safe_odds - 1

        confidence_edge = edge * adjusted_prob

        return {
            "ai_prob": ai_prob,
            "market_prob": market_prob,
            "adjusted_prob": adjusted_prob,
            "safe_odds": safe_odds,
            "odds_slip": odds_slip,
            "market_trust": self.market_trust_for_regime(regime),
            "regime": regime,
            "edge": edge,
            "confidence_edge": confidence_edge,
            "expected_value": ev,
        }

    def is_bettable(self, edge, ev):
        return edge >= self.min_edge and ev > 0
