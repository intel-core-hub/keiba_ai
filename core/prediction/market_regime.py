import numpy as np

class MarketRegime:

    def detect(self, odds_list):

        entropy = -np.sum(
            [p*np.log(p) for p in odds_list if p > 0]
        )

        if entropy < 1.5:
            return "FAVORITE"

        if entropy < 2.3:
            return "NORMAL"

        return "CHAOS"