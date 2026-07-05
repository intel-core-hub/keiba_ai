# core/meta_controller.py

import numpy as np


class MetaController:
    """
    Meta Survival Controller

    目的:
    - 全層統合制御
    - system mode switching
    - self regulation
    - adaptive participation
    - survival prioritization

    最重要思想:
    「戦略」
    より
    「状態制御」
    が重要
    """

    def __init__(self):

        # -----------------------------------------
        # global modes
        # -----------------------------------------

        self.current_state = (
            "OBSERVATION"
        )

        # -----------------------------------------
        # thresholds
        # -----------------------------------------

        self.good_survival_score = (
            0.85
        )

        self.warning_survival_score = (
            0.65
        )

        self.critical_survival_score = (
            0.40
        )

        # -----------------------------------------
        # calibration
        # -----------------------------------------

        self.max_brier = 0.22

        self.max_ece = 0.06

        # -----------------------------------------
        # streaks
        # -----------------------------------------

        self.max_loss_streak = 8

        # -----------------------------------------
        # history
        # -----------------------------------------

        self.state_history = []

    # =================================================
    # Survival Health
    # =================================================

    def survival_health(
        self,

        capital_score,
        calibration_score,
        regime_score,
    ):

        """
        各層統合
        """

        return np.mean([

            capital_score,

            calibration_score,

            regime_score,

        ])

    # =================================================
    # Calibration Health
    # =================================================

    def calibration_health(
        self,
        brier,
        ece,
    ):

        score = 1.0

        if brier > self.max_brier:
            score *= 0.6

        if ece > self.max_ece:
            score *= 0.7

        return score

    # =================================================
    # Regime Health
    # =================================================

    def regime_health(
        self,
        regime,
    ):

        penalties = {

            "NORMAL": 1.0,

            "FAVORITE_DOMINANCE":
                0.9,

            "CHAOS":
                0.6,

            "EFFICIENT":
                0.5,

            "STRESS":
                0.5,
        }

        return penalties.get(
            regime,
            0.5,
        )

    # =================================================
    # Determine State
    # =================================================

    def determine_state(
        self,

        capital_layer,
        reliability_layer,
        regime_layer,

        lose_streak=0,
    ):

        # -----------------------------------------
        # capital
        # -----------------------------------------

        capital_diag = (
            capital_layer.diagnostics()
        )

        capital_score = (
            capital_diag[
                "survival_score"
            ]
        )

        capital_mode = (
            capital_diag["mode"]
        )

        # -----------------------------------------
        # reliability
        # -----------------------------------------

        reliability = (
            reliability_layer.analyze()
        )

        ece = reliability.get(
            "expected_calibration_error",
            0,
        )

        max_gap = reliability.get(
            "max_gap",
            0,
        )

        calibration_score = (
            self.calibration_health(
                max_gap,
                ece,
            )
        )

        # -----------------------------------------
        # regime
        # -----------------------------------------

        regime = (
            regime_layer
            .status()
        )

        regime_name = regime["regime"]

        regime_score = (
            self.regime_health(
                regime_name
            )
        )

        # -----------------------------------------
        # total health
        # -----------------------------------------

        total_health = (
            self.survival_health(
                capital_score,
                calibration_score,
                regime_score,
            )
        )

        # =================================================
        # Shutdown
        # =================================================

        if capital_mode == "SHUTDOWN":

            return self.set_state(

                "SHUTDOWN",

                total_health,

                "capital shutdown",
            )

        # =================================================
        # Critical
        # =================================================

        if (
            total_health
            < self.critical_survival_score
        ):

            return self.set_state(

                "DEFENSIVE",

                total_health,

                "critical survival deterioration",
            )

        # =================================================
        # Losing streak
        # =================================================

        if (
            lose_streak
            >= self.max_loss_streak
        ):

            return self.set_state(

                "OBSERVATION",

                total_health,

                "losing streak protection",
            )

        # =================================================
        # Chaos
        # =================================================

        if regime_name in [

            "CHAOS",

            "EFFICIENT",

            "STRESS",

        ]:

            return self.set_state(

                "DEFENSIVE",

                total_health,

                f"hostile regime: {regime_name}",
            )

        # =================================================
        # Warning
        # =================================================

        if (
            total_health
            < self.warning_survival_score
        ):

            return self.set_state(

                "OBSERVATION",

                total_health,

                "reduced confidence",
            )

        # =================================================
        # Strong
        # =================================================

        if (
            total_health
            >= self.good_survival_score
        ):

            return self.set_state(

                "AGGRESSIVE",

                total_health,

                "healthy system",
            )

        # =================================================
        # Default
        # =================================================

        return self.set_state(

            "NORMAL",

            total_health,

            "stable operation",
        )

    # =================================================
    # Set State
    # =================================================

    def set_state(
        self,

        state,
        health,
        reason,
    ):

        self.current_state = state

        self.state_history.append({

            "state": state,

            "health": health,

            "reason": reason,
        })

        # memory cap
        self.state_history = (
            self.state_history[-1000:]
        )

        # -----------------------------------------
        # state parameters
        # -----------------------------------------

        params = {

            "AGGRESSIVE": {

                "bet_multiplier": 1.2,

                "participation": 1.0,

                "confidence_threshold":
                    0.02,
            },

            "NORMAL": {

                "bet_multiplier": 1.0,

                "participation": 0.8,

                "confidence_threshold":
                    0.03,
            },

            "OBSERVATION": {

                "bet_multiplier": 0.5,

                "participation": 0.4,

                "confidence_threshold":
                    0.05,
            },

            "DEFENSIVE": {

                "bet_multiplier": 0.25,

                "participation": 0.2,

                "confidence_threshold":
                    0.08,
            },

            "SHUTDOWN": {

                "bet_multiplier": 0.0,

                "participation": 0.0,

                "confidence_threshold":
                    999,
            },
        }

        return {

            "state": state,

            "health":
                round(
                    health,
                    4,
                ),

            "reason": reason,

            **params[state],
        }

    # =================================================
    # Participation Allowed
    # =================================================

    def participation_allowed(
        self,
    ):

        return self.current_state not in [

            "SHUTDOWN",

        ]

    # =================================================
    # Recommended Edge
    # =================================================

    def recommended_edge(
        self,
    ):

        mapping = {

            "AGGRESSIVE": 0.02,

            "NORMAL": 0.03,

            "OBSERVATION": 0.05,

            "DEFENSIVE": 0.08,

            "SHUTDOWN": 999,
        }

        return mapping.get(
            self.current_state,
            0.05,
        )

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(self):

        recent = self.state_history[-10:]

        return {

            "current_state":
                self.current_state,

            "recommended_edge":
                self.recommended_edge(),

            "participation_allowed":
                self.participation_allowed(),

            "recent_states":
                recent,
        }