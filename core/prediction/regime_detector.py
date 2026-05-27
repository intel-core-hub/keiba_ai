# core/regime_detector.py

import numpy as np
from collections import deque
from datetime import datetime


class RegimeDetector:
    """
    Market / Environment Regime Detector

    目的:
    - 環境変化検知
    - 生存性向上
    - リスク適応
    - 異常状態回避

    最重要:
    「世界は変化する」
    """

    def __init__(

        self,

        window_size=200,

        volatility_threshold=0.25,

        drawdown_threshold=0.20,
    ):

        # =================================================
        # rolling windows
        # =================================================

        self.window_size = (
            window_size
        )

        self.profits = deque(
            maxlen=window_size
        )

        self.edges = deque(
            maxlen=window_size
        )

        self.probabilities = deque(
            maxlen=window_size
        )

        self.outcomes = deque(
            maxlen=window_size
        )

        # =================================================
        # thresholds
        # =================================================

        self.volatility_threshold = (
            volatility_threshold
        )

        self.drawdown_threshold = (
            drawdown_threshold
        )

        # =================================================
        # states
        # =================================================

        self.current_regime = (
            "NORMAL"
        )

        self.previous_regime = (
            "NORMAL"
        )

        self.regime_history = []

    def status(self):
        diag = self.diagnostics()
        if "regime" not in diag:
            diag["regime"] = self.current_regime
        return diag

    # =================================================
    # Record Observation
    # =================================================

    def record(

        self,

        profit,
        probability,
        outcome,
        edge,
    ):

        self.profits.append(
            float(profit)
        )

        self.probabilities.append(
            float(probability)
        )

        self.outcomes.append(
            int(outcome)
        )

        self.edges.append(
            float(edge)
        )

    # =================================================
    # Detect Regime
    # =================================================

    def detect(
        self,
    ):

        if len(self.profits) < 30:

            return "WARMUP"

        # =================================================
        # metrics
        # =================================================

        profits = np.array(
            self.profits
        )

        edges = np.array(
            self.edges
        )

        outcomes = np.array(
            self.outcomes
        )

        probs = np.array(
            self.probabilities
        )

        # -----------------------------------------
        # performance
        # -----------------------------------------

        mean_profit = np.mean(
            profits
        )

        win_rate = np.mean(
            outcomes
        )

        volatility = np.std(
            profits
        )

        avg_edge = np.mean(
            edges
        )

        # -----------------------------------------
        # calibration drift
        # -----------------------------------------

        calibration_gap = np.mean(
            np.abs(
                probs - outcomes
            )
        )

        # -----------------------------------------
        # drawdown
        # -----------------------------------------

        equity = np.cumsum(
            profits
        )

        peaks = np.maximum.accumulate(
            equity
        )

        drawdowns = (
            peaks - equity
        )

        max_drawdown = np.max(
            drawdowns
        ) / max(
            np.max(peaks),
            1,
        )

        # =================================================
        # regime classification
        # =================================================

        regime = "NORMAL"

        # -----------------------------------------
        # collapse
        # -----------------------------------------

        if (

            max_drawdown
            > self.drawdown_threshold

            and mean_profit < 0

        ):

            regime = (
                "COLLAPSE"
            )

        # -----------------------------------------
        # unstable
        # -----------------------------------------

        elif (

            volatility
            > self.volatility_threshold

        ):

            regime = (
                "VOLATILE"
            )

        # -----------------------------------------
        # calibration drift
        # -----------------------------------------

        elif calibration_gap > 0.35:

            regime = (
                "DRIFT"
            )

        # -----------------------------------------
        # weak edge
        # -----------------------------------------

        elif avg_edge < 0.01:

            regime = (
                "WEAK_EDGE"
            )

        # -----------------------------------------
        # strong
        # -----------------------------------------

        elif (

            mean_profit > 0

            and win_rate > 0.35

            and calibration_gap < 0.18

        ):

            regime = (
                "FAVORABLE"
            )

        # =================================================
        # transition
        # =================================================

        if regime != self.current_regime:

            self.previous_regime = (
                self.current_regime
            )

            self.current_regime = (
                regime
            )

            self.regime_history.append({

                "timestamp":
                    datetime.utcnow()
                    .isoformat(),

                "old":
                    self.previous_regime,

                "new":
                    self.current_regime,
            })

            print(
                "\n[REGIME CHANGE]"
            )

            print(
                f"{self.previous_regime}"
                f" -> "
                f"{self.current_regime}"
            )

        return regime

    # =================================================
    # Recommended Risk
    # =================================================

    def recommended_risk(
        self,
    ):

        """
        regime別
        risk scaling
        """

        mapping = {

            "WARMUP":
                0.25,

            "NORMAL":
                1.0,

            "FAVORABLE":
                1.2,

            "VOLATILE":
                0.5,

            "WEAK_EDGE":
                0.4,

            "DRIFT":
                0.3,

            "COLLAPSE":
                0.0,
        }

        return mapping.get(

            self.current_regime,

            1.0,
        )

    # =================================================
    # Trading Allowed
    # =================================================

    def trading_allowed(
        self,
    ):

        blocked = {

            "COLLAPSE",

            "DRIFT",
        }

        return (
            self.current_regime
            not in blocked
        )

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        if len(self.profits) == 0:

            return {
                "status":
                    "NO_DATA"
            }

        profits = np.array(
            self.profits
        )

        outcomes = np.array(
            self.outcomes
        )

        probs = np.array(
            self.probabilities
        )

        calibration_gap = np.mean(
            np.abs(
                probs - outcomes
            )
        )

        return {

            "regime":
                self.current_regime,

            "samples":
                len(self.profits),

            "mean_profit":
                round(
                    np.mean(profits),
                    6,
                ),

            "volatility":
                round(
                    np.std(profits),
                    6,
                ),

            "win_rate":
                round(
                    np.mean(outcomes),
                    6,
                ),

            "calibration_gap":
                round(
                    calibration_gap,
                    6,
                ),

            "recommended_risk":
                self.recommended_risk(),

            "trading_allowed":
                self.trading_allowed(),
        }

    # =================================================
    # Survival Signal
    # =================================================

    def survival_signal(
        self,
    ):

        """
        高レベル危険信号
        """

        regime = (
            self.current_regime
        )

        mapping = {

            "FAVORABLE":
                "EXPAND",

            "NORMAL":
                "STABLE",

            "VOLATILE":
                "DEFENSIVE",

            "WEAK_EDGE":
                "REDUCE",

            "DRIFT":
                "RECALIBRATE",

            "COLLAPSE":
                "SHUTDOWN",
        }

        return mapping.get(

            regime,

            "UNKNOWN",
        )


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    detector = (
        RegimeDetector()
    )

    np.random.seed(42)

    # =================================================
    # simulate environment
    # =================================================

    for i in range(300):

        # normal
        if i < 100:

            profit = np.random.normal(
                0.2,
                0.8,
            )

        # volatile
        elif i < 200:

            profit = np.random.normal(
                0,
                2.0,
            )

        # collapse
        else:

            profit = np.random.normal(
                -1.0,
                1.5,
            )

        probability = np.clip(

            np.random.normal(
                0.35,
                0.1,
            ),

            0.01,
            0.99,
        )

        outcome = int(
            np.random.rand()
            < probability
        )

        edge = np.random.normal(
            0.03,
            0.02,
        )

        detector.record(

            profit=profit,

            probability=(
                probability
            ),

            outcome=outcome,

            edge=edge,
        )

        if i % 20 == 0:

            regime = (
                detector.detect()
            )

            print(
                detector.diagnostics()
            )

            print(
                "signal:",
                detector.survival_signal()
            )