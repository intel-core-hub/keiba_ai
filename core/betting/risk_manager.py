# core/risk_manager.py

from dataclasses import dataclass


# =====================================================
# 設定
# =====================================================

@dataclass
class RiskConfig:

    initial_bankroll: float = 20000

    # ---- Drawdown制御 ----
    dd_soft: float = 0.15
    dd_hard: float = 0.25
    dd_stop: float = 0.35

    # ---- 利益ロック ----
    profit_lock: float = 0.30

    # ---- 連敗制御 ----
    lose_streak_soft: int = 3
    lose_streak_hard: int = 5

    # ---- 1R最大リスク ----
    max_risk_fraction: float = 0.10


# =====================================================
# Risk Manager
# =====================================================

class RiskManager:

    def __init__(self, config: RiskConfig):

        self.cfg = config

        # ---- 資金 ----
        self.initial_bankroll = config.initial_bankroll
        self.bankroll = config.initial_bankroll

        # 利益ロック基準（重要）
        self.locked_bankroll = self.initial_bankroll

        # Peak追跡（DD計算）
        self.peak_bankroll = self.bankroll

        # ---- ストリーク ----
        self.win_streak = 0
        self.lose_streak = 0

        self.total_bets = 0

        # ---- レース単位リスク管理 ----
        self.current_race_risk = 0

    # =================================================
    # レース開始時リセット（重要）
    # =================================================

    def reset_race_risk(self):
        self.current_race_risk = 0

    # =================================================
    # 結果更新
    # =================================================

    def update_after_race(self, profit: float):

        self.bankroll += profit
        self.total_bets += 1

        # ---- 勝敗更新 ----
        if profit > 0:
            self.win_streak += 1
            self.lose_streak = 0
        else:
            self.lose_streak += 1
            self.win_streak = 0

        # ---- Peak更新 ----
        self.peak_bankroll = max(
            self.peak_bankroll,
            self.bankroll,
        )

        # ---- Profit Lock（安全版）----
        if self.bankroll > self.locked_bankroll * (
            1 + self.cfg.profit_lock
        ):
            self.locked_bankroll = self.bankroll

    # =================================================
    # Drawdown
    # =================================================

    def drawdown(self) -> float:

        if self.peak_bankroll <= 0:
            return 0.0

        dd = 1 - self.bankroll / self.peak_bankroll

        return max(0.0, dd)

    # =================================================
    # 利益率（ロック基準）
    # =================================================

    def profit_ratio(self) -> float:

        return (
            self.bankroll / self.locked_bankroll
        ) - 1

    # =================================================
    # リスク倍率（最重要）
    # =================================================

    def risk_multiplier(self) -> float:

        dd = self.drawdown()
        profit = self.profit_ratio()

        multiplier = 1.0

        # ---- 強制停止 ----
        if dd >= self.cfg.dd_stop:
            return 0.0

        # ---- 滑らかなDD防御（プロ仕様）----
        multiplier *= max(0.2, 1 - dd * 2)

        # ---- 連敗防御 ----
        if self.lose_streak >= self.cfg.lose_streak_hard:
            multiplier *= 0.5

        elif self.lose_streak >= self.cfg.lose_streak_soft:
            multiplier *= 0.75

        # ---- 勝ち過ぎ暴走防止 ----
        if profit >= self.cfg.profit_lock:
            multiplier *= 0.7

        return multiplier

    # =================================================
    # レース内最大賭け金
    # =================================================

    def max_bet_size(self):

        remaining = (
            self.bankroll * self.cfg.max_risk_fraction
            - self.current_race_risk
        )

        return max(0, remaining)

    # =================================================
    # Bet登録（超重要）
    # =================================================

    def register_bet(self, size: float):

        self.current_race_risk += size

    # =================================================
    # 購入可能？
    # =================================================

    def can_bet(self) -> bool:

        if self.bankroll <= 0:
            return False

        if self.risk_multiplier() <= 0:
            return False

        if self.max_bet_size() <= 0:
            return False

        return True

    # =================================================
    # ステータス（ログ用）
    # =================================================

    def status(self):

        return {
            "bankroll": round(self.bankroll, 2),
            "drawdown": round(self.drawdown(), 3),
            "profit_ratio": round(self.profit_ratio(), 3),
            "win_streak": self.win_streak,
            "lose_streak": self.lose_streak,
            "risk_multiplier": round(
                self.risk_multiplier(), 3
            ),
            "race_risk_used": round(
                self.current_race_risk, 2
            ),
        }