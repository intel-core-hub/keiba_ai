class PortfolioManager:

    def __init__(self, strategies, evaluator, regime, risk):

        self.strategies = strategies
        self.evaluator = evaluator
        self.regime = regime
        self.risk = risk

    def update_regime(self, races):
        try:
            self.market_state = self.regime.detect(races)
        except TypeError:
            detector_status = getattr(self.regime, "status", None)
            if callable(detector_status):
                self.market_state = detector_status()
            else:
                self.market_state = {
                    "regime": getattr(self.regime, "current_regime", "NORMAL")
                }

    def evaluate_strategies(self):
        self.scores = self.evaluator.score(self.strategies)

    def allocate_capital(self):
        return self.evaluator.allocate(self.scores)

    def execute(self, races, allocations):

        decisions = []

        for strat in self.strategies:

            weight = allocations[strat.name]

            d = strat.run(races, weight)

            decisions.extend(d)

        return decisions