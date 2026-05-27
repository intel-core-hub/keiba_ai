# core/portfolio_allocator.py

import numpy as np


class PortfolioAllocator:
    """
    Survival Portfolio Allocator

    目的:
    - 相関リスク抑制
    - 同時崩壊防止
    - exposure control
    - bankroll survival

    最重要思想:
    「良いベット」
    を増やすより

    「同時死」
    を防ぐ
    """

    def __init__(self):

        # -----------------------------------------
        # exposure limits
        # -----------------------------------------

        self.max_total_exposure = 0.15

        self.max_race_exposure = 0.06

        self.max_single_bet = 0.03

        # -----------------------------------------
        # regime multipliers
        # -----------------------------------------

        self.regime_scaling = {

            "NORMAL": 1.0,

            "FAVORITE_DOMINANCE": 0.8,

            "CHAOS": 0.5,

            "EFFICIENT": 0.4,

            "STRESS": 0.5,
        }

        # -----------------------------------------
        # correlation penalty
        # -----------------------------------------

        self.same_race_penalty = 0.65

        self.same_odds_zone_penalty = (
            0.80
        )

    # =================================================
    # Odds Zone
    # =================================================

    def odds_zone(
        self,
        odds,
    ):

        if odds < 3:
            return "favorite"

        if odds < 10:
            return "mid"

        return "longshot"

    # =================================================
    # Exposure
    # =================================================

    def exposure_ratio(
        self,
        total_stakes,
        bankroll,
    ):

        if bankroll <= 0:
            return 1.0

        return total_stakes / bankroll

    # =================================================
    # Correlation Penalty
    # =================================================

    def correlation_penalty(
        self,
        decision,
        existing_decisions,
    ):

        penalty = 1.0

        for d in existing_decisions:

            # -----------------------------------------
            # same race
            # -----------------------------------------

            if (
                d.race_id
                == decision.race_id
            ):

                penalty *= (
                    self.same_race_penalty
                )

            # -----------------------------------------
            # same odds zone
            # -----------------------------------------

            if (
                self.odds_zone(d.odds)
                ==
                self.odds_zone(
                    decision.odds
                )
            ):

                penalty *= (
                    self.same_odds_zone_penalty
                )

        return penalty

    # =================================================
    # Regime Scaling
    # =================================================

    def regime_multiplier(
        self,
        regime,
    ):

        return self.regime_scaling.get(
            regime,
            1.0
        )

    # =================================================
    # Allocation Check
    # =================================================

    def can_allocate(
        self,
        decision,
        existing_decisions,
        current_bankroll,
    ):
        """
        ベット可能かチェック

        - exposure check
        - correlation check
        - regime check
        """

        # -----------------------------------------
        # exposure
        # -----------------------------------------

        exposure = self.exposure_ratio(
            decision.bet_size,
            current_bankroll,
        )

        if (
            exposure
            > self.max_single_bet
        ):
            return False

        # -----------------------------------------
        # correlation penalty
        # -----------------------------------------

        cp = self.correlation_penalty(
            decision,
            existing_decisions,
        )

        adjusted_size = (
            decision.bet_size * cp
        )

        total_exposure = (
            sum([d.bet_size for d in existing_decisions])
            + adjusted_size
        ) / current_bankroll

        if (
            total_exposure
            > self.max_total_exposure
        ):
            return False

        return True

    def allocate(
        self,
        decisions,
        bankroll,
        regime="NORMAL",
    ):
        allocated = []
        regime_mult = self.regime_multiplier(regime)

        for d in decisions:
            d.bet_size = d.bet_size * regime_mult

            if d.bet_size <= 0:
                continue

            if not self.can_allocate(d, allocated, bankroll):
                continue

            penalty = self.correlation_penalty(d, allocated)
            d.bet_size = d.bet_size * penalty

            if d.bet_size <= 0:
                continue

            allocated.append(d)

        return allocated
