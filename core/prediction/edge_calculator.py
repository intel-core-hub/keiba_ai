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
        max_edge_clip=0.25,
    ):
        self.min_edge = min_edge
        self.market_trust = market_trust
        self.max_edge_clip = max_edge_clip

    def odds_to_prob(self, odds):
        if odds <= 1.0:
            return 0.0
        return 1.0 / odds

    def blend_with_market(self, ai_prob, market_prob):

        return (
            (1 - self.market_trust) * ai_prob
            + self.market_trust * market_prob
        )

    def calculate_edge(self, ai_prob, odds):

        market_prob = self.odds_to_prob(odds)

        adjusted_prob = self.blend_with_market(
            ai_prob,
            market_prob,
        )

        edge = adjusted_prob - market_prob

        edge = np.clip(
            edge,
            -self.max_edge_clip,
            self.max_edge_clip,
        )

        ev = adjusted_prob * odds - 1

        confidence_edge = edge * adjusted_prob

        return {
            "ai_prob": ai_prob,
            "market_prob": market_prob,
            "adjusted_prob": adjusted_prob,
            "edge": edge,
            "confidence_edge": confidence_edge,
            "expected_value": ev,
        }

    def is_bettable(self, edge, ev):
        return edge >= self.min_edge and ev > 0