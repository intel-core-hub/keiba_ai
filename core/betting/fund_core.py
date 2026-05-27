class FundCore:

    def __init__(self, bankroll):
        self.bankroll = bankroll
        self.daily_exposure_limit = 0.12
        self.risk_budget = 0.03

        self.exposure = 0
        self.daily_loss = 0

    # ----------------------
    # 投資可能か
    # ----------------------
    def allow_bet(self, stake):

        if self.exposure + stake > self.bankroll * self.daily_exposure_limit:
            return False

        if abs(self.daily_loss) > self.bankroll * self.risk_budget:
            return False

        return True

    # ----------------------
    # 賭け実行
    # ----------------------
    def register_bet(self, stake):
        self.exposure += stake

    # ----------------------
    # 結果反映
    # ----------------------
    def update_result(self, profit):
        self.bankroll += profit
        self.daily_loss += min(0, profit)

    # ----------------------
    # 開催リセット
    # ----------------------
    def reset_day(self):
        self.exposure = 0
        self.daily_loss = 0