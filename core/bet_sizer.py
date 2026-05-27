# core/bet_sizer.py

from dataclasses import dataclass
import math


# =====================================================
# 設定
# =====================================================

@dataclass
class BetConfig:

    # --- Kelly設定 ---
    kelly_fraction: float = 0.25     # 1/4 Kelly
    min_edge: float = 0.02           # 最低期待値
    min_odds: float = 1.0            # 低オッズ制限（0で無効）

    # --- 安全制御 ---
    max_fraction: float = 0.15       # 単一ベット上限
    max_race_exposure: float = 0.25  # ★1R総投資上限（最重要）
    min_bet: int = 100               # 最低購入額
    round_unit: int = 100            # 馬券単位

    # --- AI過信防止 ---
    probability_shrink: float = 0.90
    odds_slip: float = 0.00

    # --- 分散制御 ---
    variance_penalty: float = 0.15


# =====================================================
# BetSizer
# =====================================================

class BetSizer:

    def __init__(self, risk_manager=None, config: BetConfig = None):

        if config is None:
            config = BetConfig()

        self.cfg = config
        self.risk_manager = risk_manager

        # ★レース単位リスク追跡
        self.current_race_exposure = 0

    # -------------------------------------------------
    # レース開始時に呼ぶ（重要）
    # -------------------------------------------------

    def reset_race(self):
        """1レース開始時に必ず呼ぶ"""
        self.current_race_exposure = 0

    # -------------------------------------------------
    # Edge計算
    # -------------------------------------------------

    def expected_edge(self, prob: float, odds: float):

        odds *= (1 - self.cfg.odds_slip)

        return prob * odds - 1

    # -------------------------------------------------
    # AI過信防止
    # -------------------------------------------------

    def adjusted_probability(self, prob: float):

        # AIは必ず確率を盛る
        return prob * self.cfg.probability_shrink

    # -------------------------------------------------
    # Kelly
    # -------------------------------------------------

    def kelly_fraction_raw(self, prob: float, odds: float):

        b = odds - 1
        q = 1 - prob

        if b <= 0:
            return 0

        kelly = (b * prob - q) / b

        return max(kelly, 0)

    # -------------------------------------------------
    # 分散制御
    # -------------------------------------------------

    def variance_adjustment(self, odds: float):

        # 高オッズほど危険
        penalty = 1 / (
            1 + self.cfg.variance_penalty * math.log(odds + 1)
        )

        return penalty

    # -------------------------------------------------
    # 最終ベット計算（完成版）
    # -------------------------------------------------

    def calculate_bet(
        self,
        bankroll: float,
        prob: float,
        odds: float,
        risk_multiplier: float,
    ):

        # --- オッズ制限 ---
        if odds < self.cfg.min_odds:
            return 0

        # --- 確率補正 ---
        prob = self.adjusted_probability(prob)

        # --- Edge ---
        edge = self.expected_edge(prob, odds)

        if edge < self.cfg.min_edge:
            return 0

        # --- Kelly ---
        raw_kelly = self.kelly_fraction_raw(prob, odds)

        if raw_kelly <= 0:
            return 0

        # --- Fractional Kelly ---
        fraction = raw_kelly * self.cfg.kelly_fraction

        # --- 分散制御 ---
        fraction *= self.variance_adjustment(odds)

        # --- RiskManager連動 ---
        fraction *= risk_multiplier

        # --- 単一ベット上限 ---
        fraction = min(fraction, self.cfg.max_fraction)

        bet_size = bankroll * fraction

        # --- 馬券単位丸め ---
        bet_size = int(
            bet_size // self.cfg.round_unit
        ) * self.cfg.round_unit

        if bet_size < self.cfg.min_bet:
            return 0

        # =====================================================
        # ★ 最重要：レース単位 Exposure Cap
        # =====================================================

        max_allowed = bankroll * self.cfg.max_race_exposure

        remaining = max_allowed - self.current_race_exposure

        if remaining <= 0:
            return 0

        if bet_size > remaining:
            bet_size = int(
                remaining // self.cfg.round_unit
            ) * self.cfg.round_unit

        if bet_size < self.cfg.min_bet:
            return 0

        # exposure更新
        self.current_race_exposure += bet_size

        return bet_size

    def size_bet(
        self,
        probability: float,
        odds: float,
        edge: float = None,
    ):
        # Compatibility wrapper used by main.SurvivalOS
        bankroll = 0.0
        risk_multiplier = 1.0

        if self.risk_manager is not None:
            bankroll = getattr(self.risk_manager, "bankroll", 0.0)
            risk_multiplier = getattr(self.risk_manager, "risk_multiplier", lambda: 1.0)()

        if bankroll <= 0:
            bankroll = 10000.0

        return self.calculate_bet(
            bankroll=bankroll,
            prob=probability,
            odds=odds,
            risk_multiplier=risk_multiplier,
        )