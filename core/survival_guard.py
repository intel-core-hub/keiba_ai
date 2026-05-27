class SurvivalGuard:
    def __init__(self, max_stake_fraction: float = 0.15):
        self.max_stake_fraction = max_stake_fraction

    def allow_trade(self, bankroll: float, stake: float) -> bool:
        if bankroll <= 0 or stake <= 0:
            return False
        return stake <= bankroll * self.max_stake_fraction
