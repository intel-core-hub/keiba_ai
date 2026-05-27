class BankrollManager:

    def __init__(self, initial_bankroll):
        self.initial = initial_bankroll
        self.peak = initial_bankroll

    def phase(self, bankroll):

        dd = (bankroll - self.peak) / self.peak

        if bankroll > self.peak:
            self.peak = bankroll

        growth = bankroll / self.initial

        # -------- Phase 判定 --------
        if dd < -0.15:
            return "SURVIVAL"

        if growth < 1.05:
            return "STABLE"

        if growth < 1.3:
            return "EXPANSION"

        return "EVOLUTION"

    def kelly_multiplier(self, phase):

        return {
            "SURVIVAL": 0.25,
            "STABLE": 0.5,
            "EXPANSION": 0.8,
            "EVOLUTION": 1.0,
        }[phase]