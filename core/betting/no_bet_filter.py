# core/no_bet_filter.py

import numpy as np


class NoBetFilter:
    """
    Survival No-Bet Filter

    目的:
    - 無理な参加を防ぐ
    - 不安定局面回避
    - calibration崩壊回避
    - market efficiency回避
    - survival優先

    最重要思想:
    「賭けない能力」
    は
    「予測能力」
    より重要
    """

    def __init__(self):

        # -----------------------------------------
        # minimum requirements
        # -----------------------------------------

        self.min_edge = 0.03

        self.min_probability = 0.05

        self.max_odds = 30

        self.min_odds = 1.5

        # -----------------------------------------
        # market efficiency
        # -----------------------------------------

        self.market_efficiency_limit = (
            0.015
        )

        # -----------------------------------------
        # calibration
        # -----------------------------------------

        self.max_brier = 0.22

        self.max_uncertainty = 0.65

        self.min_edge_quality = 0.45

        # -----------------------------------------
        # drawdown protection
        # -----------------------------------------

        self.stress_drawdown = 0.15

        self.panic_drawdown = 0.30

        # -----------------------------------------
        # streak protection
        # -----------------------------------------

        self.max_lose_streak = 8

    # =================================================
    # Market Efficiency
    # =================================================

    def market_too_efficient(
        self,
        probability,
        market_probability,
    ):

        """
        市場との差が小さい

        = 優位性が不明
        """

        diff = abs(
            probability
            - market_probability
        )

        return (
            diff
            < self.market_efficiency_limit
        )

    # =================================================
    # Odds Filter
    # =================================================

    def invalid_odds(
        self,
        odds,
    ):

        return (
            odds < self.min_odds
            or odds > self.max_odds
        )

    # =================================================
    # Probability Filter
    # =================================================

    def invalid_probability(
        self,
        probability,
    ):

        return (
            probability
            < self.min_probability
        )

    # =================================================
    # Edge Filter
    # =================================================

    def insufficient_edge(
        self,
        edge,
    ):

        return edge < self.min_edge

    # =================================================
    # Calibration Collapse
    # =================================================

    def calibration_danger(
        self,
        brier_score,
    ):

        if brier_score is None:
            return False

        return (
            brier_score
            > self.max_brier
        )

    # =================================================
    # Drawdown Stress
    # =================================================

    def drawdown_danger(
        self,
        drawdown,
    ):

        return (
            drawdown
            > self.stress_drawdown
        )

    # =================================================
    # Panic Mode
    # =================================================

    def panic_mode(
        self,
        drawdown,
    ):

        return (
            drawdown
            > self.panic_drawdown
        )

    # =================================================
    # Losing Streak
    # =================================================

    def streak_danger(
        self,
        lose_streak,
    ):

        return (
            lose_streak
            >= self.max_lose_streak
        )

    # =================================================
    # Volatility Spike
    # =================================================

    def volatility_danger(
        self,
        recent_profits,
    ):

        if len(recent_profits) < 30:
            return False

        recent_std = np.std(
            recent_profits[-20:]
        )

        overall_std = np.std(
            recent_profits
        )

        if overall_std == 0:
            return False

        return (
            recent_std
            > overall_std * 1.8
        )

    # =================================================
    # Final Decision
    # =================================================

    def should_skip(
        self,

        probability,
        odds,
        edge,

        bankroll_status,

        brier_status=None,

        recent_profits=None,

        uncertainty_score=None,

        edge_quality=None,

        drift_score=None,

        defensive_mode=None,
    ):

        """
        True = 賭けない
        False = 賭ける可能性あり
        """

        market_probability = (
            1 / odds
        )

        # -----------------------------------------
        # hard filters
        # -----------------------------------------

        if self.invalid_odds(
            odds
        ):

            return True, "INVALID_ODDS"

        if self.invalid_probability(
            probability
        ):

            return True, (
                "LOW_PROBABILITY"
            )

        if self.insufficient_edge(
            edge
        ):

            return True, (
                "INSUFFICIENT_EDGE"
            )

        # -----------------------------------------
        # market efficiency
        # -----------------------------------------

        if self.market_too_efficient(
            probability,
            market_probability,
        ):

            return True, (
                "MARKET_TOO_EFFICIENT"
            )

        # -----------------------------------------
        # calibration collapse
        # -----------------------------------------

        if self.calibration_danger(
            brier_status
        ):

            return True, (
                "CALIBRATION_DANGER"
            )

        # -----------------------------------------
        # uncertainty
        # -----------------------------------------

        if uncertainty_score is not None:

            if uncertainty_score > self.max_uncertainty:

                return True, (
                    "HIGH_UNCERTAINTY"
                )

        if defensive_mode == "HALT":
            return True, "DEFENSIVE_HALT"

        if defensive_mode == "DEFENSIVE" and edge < 0.08:
            return True, "DEFENSIVE_MODE"

        if uncertainty_score is not None and drift_score is not None:
            if uncertainty_score >= 0.50 and drift_score >= 0.08:
                return True, "UNCERTAINTY_DRIFT"

        # -----------------------------------------
        # edge quality
        # -----------------------------------------

        if edge_quality is not None:

            if edge_quality < self.min_edge_quality:

                return True, (
                    "LOW_EDGE_QUALITY"
                )

        # -----------------------------------------
        # drawdown
        # -----------------------------------------

        drawdown = bankroll_status.get(
            "drawdown",
            0,
        )

        if self.panic_mode(
            drawdown
        ):

            return True, (
                "PANIC_DRAWDOWN"
            )

        if self.drawdown_danger(
            drawdown
        ):

            # stress mode:
            # 高edgeのみ許可

            if edge < 0.06:

                return True, (
                    "STRESS_DRAWDOWN"
                )

        # -----------------------------------------
        # streak
        # -----------------------------------------

        lose_streak = (
            bankroll_status.get(
                "lose_streak",
                0,
            )
        )

        if self.streak_danger(
            lose_streak
        ):

            return True, (
                "LOSE_STREAK"
            )

        # -----------------------------------------
        # volatility
        # -----------------------------------------

        if recent_profits:

            if self.volatility_danger(
                recent_profits
            ):

                return True, (
                    "VOLATILITY_SPIKE"
                )

        # -----------------------------------------
        # safe
        # -----------------------------------------

        return False, "OK"

    # =================================================
    # Status
    # =================================================

    def status(self):

        return {

            "min_edge": (
                self.min_edge
            ),

            "max_brier": (
                self.max_brier
            ),

            "stress_drawdown": (
                self.stress_drawdown
            ),

            "panic_drawdown": (
                self.panic_drawdown
            ),

            "market_efficiency_limit": (
                self.market_efficiency_limit
            ),

            "max_uncertainty": (
                self.max_uncertainty
            ),

            "min_edge_quality": (
                self.min_edge_quality
            ),
        }