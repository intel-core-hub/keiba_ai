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
            1.0,
        )

    # =================================================
    # Allocate
    # =================================================

    def allocate(
        self,

        decisions,

        bankroll,

        regime="NORMAL",
    ):

        """
        decisions:
        [
            Decision(...)
        ]
        """

        if len(decisions) == 0:
            return []

        # -----------------------------------------
        # sort by edge quality
        # -----------------------------------------

        decisions = sorted(
            decisions,
            key=lambda x: x.edge,
            reverse=True,
        )

        allocated = []

        total_allocated = 0

        regime_mult = (
            self.regime_multiplier(
                regime
            )
        )

        # =================================================
        # Allocation Loop
        # =================================================

        for d in decisions:

            # -----------------------------------------
            # base size
            # -----------------------------------------

            base_size = d.bet_size

            # -----------------------------------------
            # regime scaling
            # -----------------------------------------

            adjusted = (
                base_size
                * regime_mult
            )

            # -----------------------------------------
            # correlation penalty
            # -----------------------------------------

            penalty = (
                self.correlation_penalty(
                    d,
                    allocated,
                )
            )

            adjusted *= penalty

            # -----------------------------------------
            # single bet cap
            # -----------------------------------------

            max_single = (
                bankroll
                * self.max_single_bet
            )

            adjusted = min(
                adjusted,
                max_single,
            )

            # -----------------------------------------
            # race exposure
            # -----------------------------------------

            race_exposure = sum(

                x.bet_size

                for x in allocated

                if (
                    x.race_id
                    == d.race_id
                )
            )

            race_limit = (
                bankroll
                * self.max_race_exposure
            )

            if (
                race_exposure
                + adjusted
                > race_limit
            ):

                adjusted = max(
                    0,
                    race_limit
                    - race_exposure,
                )

            # -----------------------------------------
            # total exposure
            # -----------------------------------------

            total_limit = (
                bankroll
                * self.max_total_exposure
            )

            if (
                total_allocated
                + adjusted
                > total_limit
            ):

                adjusted = max(
                    0,
                    total_limit
                    - total_allocated,
                )

            # -----------------------------------------
            # skip tiny positions
            # -----------------------------------------

            if adjusted < 1:
                continue

            # -----------------------------------------
            # apply
            # -----------------------------------------

            d.bet_size = round(
                adjusted,
                2,
            )

            allocated.append(d)

            total_allocated += adjusted

        return allocated

    # =================================================
    # Portfolio Risk
    # =================================================

    def portfolio_risk(
        self,
        decisions,
        bankroll,
    ):

        total = sum(
            d.bet_size
            for d in decisions
        )

        exposure = (
            self.exposure_ratio(
                total,
                bankroll,
            )
        )

        race_count = len(set(
            d.race_id
            for d in decisions
        ))

        avg_edge = np.mean([
            d.edge
            for d in decisions
        ]) if decisions else 0

        return {

            "total_exposure":
                round(exposure, 4),

            "race_count":
                race_count,

            "avg_edge":
                round(avg_edge, 4),

            "decision_count":
                len(decisions),
        }

    # =================================================
    # Status
    # =================================================

    def status(self):

        return {

            "max_total_exposure":
                self.max_total_exposure,

            "max_race_exposure":
                self.max_race_exposure,

            "max_single_bet":
                self.max_single_bet,

            "same_race_penalty":
                self.same_race_penalty,

            "same_odds_zone_penalty":
                self.same_odds_zone_penalty,
        }