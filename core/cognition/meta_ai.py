import numpy as np


class MetaAI:

    def __init__(self):
        self.prev_probs = []

    # --------------------------
    # Stability
    # --------------------------
    def stability_score(self, prob):

        if not self.prev_probs:
            self.prev_probs.append(prob)
            return 1.0

        change = abs(prob - self.prev_probs[-1])
        self.prev_probs.append(prob)

        return max(0.0, 1 - change * 2)

    # --------------------------
    # Edge Explosion
    # --------------------------
    def edge_score(self, edges):

        if len(edges) == 0:
            return 1.0

        mean_edge = np.mean(edges)

        if mean_edge > 0.15:
            return 0.5

        return 1.0

    # --------------------------
    # Market Agreement
    # --------------------------
    def market_score(self, ai_prob, market_prob):

        diff = abs(ai_prob - market_prob)
        return max(0.0, 1 - diff * 3)

    # --------------------------
    # Final Judge
    # --------------------------
    def approve(
        self,
        ai_prob,
        market_prob,
        edges,
        model_health,
        drawdown,
    ):

        scores = []

        scores.append(self.stability_score(ai_prob))
        scores.append(self.edge_score(edges))
        scores.append(self.market_score(ai_prob, market_prob))
        scores.append(model_health)

        # 資金ストレス
        if drawdown < -0.15:
            scores.append(0.6)
        else:
            scores.append(1.0)

        final_score = np.mean(scores)

        return final_score > 0.65, final_score