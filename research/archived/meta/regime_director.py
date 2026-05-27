class RegimeDirector:

    def detect(self, races):

        avg_odds = sum(
            c["odds"]
            for r in races.values()
            for c in r
        ) / 100

        if avg_odds > 20:
            return "chaos"

        return "stable"