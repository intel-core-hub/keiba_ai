class AIEvaluator:

    def score(self, strategies):

        scores = {}

        for s in strategies:

            m = s.metrics()

            roi = m.get("roi", 0.0)
            sharpe = m.get("sharpe", 0.0)
            profit = m.get("profit", 0.0)
            drawdown = m.get("drawdown", 0.0)
            volatility = m.get("volatility", 0.0)
            brier = m.get("brier", 0.2)
            ece = m.get("ece", 0.05)

            score = (
                0.45 * roi
                + 0.20 * sharpe
                + 0.10 * profit
                - 0.15 * drawdown
                - 0.05 * volatility
                - 0.03 * brier
                - 0.02 * ece
            )

            scores[s.name] = score

        return scores

    def allocate(self, scores):

        total = sum(max(v,0) for v in scores.values())

        if total == 0:
            n = len(scores)
            return {k: 1 / n for k in scores} if n else {}

        return {
            k: max(v,0)/total
            for k,v in scores.items()
        }