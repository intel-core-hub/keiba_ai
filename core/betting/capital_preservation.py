# core/capital_preservation.py

import numpy as np


class CapitalPreservation:
    """
    Capital Preservation Layer

    目的:
    - 資本死回避
    - emergency reserve
    - recovery mode
    - forced slowdown
    - shutdown protection

    最重要思想:
    「利益」
    より
    「次も生きている」
    """

    def __init__(
        self,
        initial_capital=20000,
    ):

        # -----------------------------------------
        # capital
        # -----------------------------------------

        self.initial_capital = (
            initial_capital
        )

        self.current_capital = (
            initial_capital
        )

        self.peak_capital = (
            initial_capital
        )

        # -----------------------------------------
        # reserve structure
        # -----------------------------------------

        self.reserve_ratio = 0.35

        self.emergency_ratio = 0.15

        # -----------------------------------------
        # drawdown zones
        # -----------------------------------------

        self.warning_dd = 0.10

        self.stress_dd = 0.20

        self.critical_dd = 0.35

        self.shutdown_dd = 0.50

        # -----------------------------------------
        # recovery rules
        # -----------------------------------------

        self.recovery_factor = 0.5

        self.max_growth_rate = 0.03

        # -----------------------------------------
        # history
        # -----------------------------------------

        self.capital_history = [
            initial_capital
        ]

        self.mode_history = []

    # =================================================
    # Update
    # =================================================

    def update(
        self,
        profit,
    ):

        self.current_capital += profit

        self.peak_capital = max(
            self.peak_capital,
            self.current_capital,
        )

        self.capital_history.append(
            self.current_capital
        )

        self.mode_history.append(
            self.current_mode()
        )

        # memory cap
        self.capital_history = (
            self.capital_history[-5000:]
        )

        self.mode_history = (
            self.mode_history[-5000:]
        )

    # =================================================
    # Drawdown
    # =================================================

    def drawdown(self):

        if self.peak_capital <= 0:
            return 1.0

        return (

            self.peak_capital
            - self.current_capital

        ) / self.peak_capital

    # =================================================
    # Reserve Capital
    # =================================================

    def reserve_capital(self):

        return (
            self.current_capital
            * self.reserve_ratio
        )

    # =================================================
    # Tradable Capital
    # =================================================

    def tradable_capital(self):

        reserve = self.reserve_capital()

        tradable = (
            self.current_capital
            - reserve
        )

        return max(
            tradable,
            0,
        )

    # =================================================
    # Emergency Capital
    # =================================================

    def emergency_capital(self):

        return (
            self.current_capital
            * self.emergency_ratio
        )

    # =================================================
    # Current Mode
    # =================================================

    def current_mode(self):

        dd = self.drawdown()

        # -----------------------------------------
        # shutdown
        # -----------------------------------------

        if dd >= self.shutdown_dd:

            return {
                "mode": "SHUTDOWN",

                "risk_multiplier": 0.0,

                "description":
                    "system halted",
            }

        # -----------------------------------------
        # critical
        # -----------------------------------------

        if dd >= self.critical_dd:

            return {
                "mode": "CRITICAL",

                "risk_multiplier": 0.2,

                "description":
                    "extreme capital defense",
            }

        # -----------------------------------------
        # stress
        # -----------------------------------------

        if dd >= self.stress_dd:

            return {
                "mode": "STRESS",

                "risk_multiplier": 0.4,

                "description":
                    "survival focus",
            }

        # -----------------------------------------
        # warning
        # -----------------------------------------

        if dd >= self.warning_dd:

            return {
                "mode": "WARNING",

                "risk_multiplier": 0.7,

                "description":
                    "risk reduction active",
            }

        # -----------------------------------------
        # normal
        # -----------------------------------------

        return {
            "mode": "NORMAL",

            "risk_multiplier": 1.0,

            "description":
                "normal operation",
        }

    # =================================================
    # Capital Allocation
    # =================================================

    def adjust_bet_size(
        self,
        proposed_size,
    ):

        mode = self.current_mode()

        adjusted = (

            proposed_size
            * mode["risk_multiplier"]

        )

        # -----------------------------------------
        # tradable capital limit
        # -----------------------------------------

        tradable = self.tradable_capital()

        adjusted = min(
            adjusted,
            tradable
            * self.max_growth_rate,
        )

        return max(
            adjusted,
            0,
        )

    # =================================================
    # Recovery Requirement
    # =================================================

    def recovery_needed(self):

        return max(

            self.peak_capital
            - self.current_capital,

            0,
        )

    # =================================================
    # Recovery Progress
    # =================================================

    def recovery_progress(self):

        if self.peak_capital <= 0:
            return 0

        return (
            self.current_capital
            / self.peak_capital
        )

    # =================================================
    # Survival Probability
    # =================================================

    def survival_score(self):

        dd = self.drawdown()

        score = 1.0

        # -----------------------------------------
        # drawdown penalty
        # -----------------------------------------

        if dd > 0.10:
            score *= 0.85

        if dd > 0.20:
            score *= 0.70

        if dd > 0.35:
            score *= 0.50

        if dd > 0.50:
            score *= 0.10

        # -----------------------------------------
        # volatility penalty
        # -----------------------------------------

        if len(self.capital_history) > 50:

            recent = np.diff(
                self.capital_history[-50:]
            )

            vol = np.std(recent)

            if vol > (
                self.initial_capital
                * 0.03
            ):

                score *= 0.80

        return round(
            max(score, 0),
            4,
        )

    # =================================================
    # Forced Shutdown
    # =================================================

    def should_shutdown(self):

        return (
            self.current_mode()["mode"]
            == "SHUTDOWN"
        )

    # =================================================
    # Safe To Trade
    # =================================================

    def safe_to_trade(self):

        mode = self.current_mode()

        return mode["mode"] not in [

            "SHUTDOWN",

        ]

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(self):

        mode = self.current_mode()

        return {

            "current_capital":
                round(
                    self.current_capital,
                    2,
                ),

            "peak_capital":
                round(
                    self.peak_capital,
                    2,
                ),

            "drawdown":
                round(
                    self.drawdown(),
                    4,
                ),

            "reserve_capital":
                round(
                    self.reserve_capital(),
                    2,
                ),

            "tradable_capital":
                round(
                    self.tradable_capital(),
                    2,
                ),

            "emergency_capital":
                round(
                    self.emergency_capital(),
                    2,
                ),

            "mode":
                mode["mode"],

            "mode_description":
                mode["description"],

            "risk_multiplier":
                mode["risk_multiplier"],

            "recovery_needed":
                round(
                    self.recovery_needed(),
                    2,
                ),

            "recovery_progress":
                round(
                    self.recovery_progress(),
                    4,
                ),

            "survival_score":
                self.survival_score(),
        }