# core/self_destruct.py

import numpy as np


class SelfDestructSystem:
    """
    Survival Protection Layer

    目的:
    - モデル崩壊検知
    - calibration collapse 検知
    - variance explosion 検知
    - bankroll instability 検知
    - regime mismatch 検知

    最重要思想:
    「利益最大化」ではなく
    「自己破壊防止」
    """

    def __init__(self):

        # -----------------------------
        # performance tracking
        # -----------------------------

        self.expected_edges = []
        self.real_profits = []

        self.probabilities = []
        self.hits = []

        self.bankroll_history = []

        self.regime_history = []

        # -----------------------------
        # system state
        # -----------------------------

        self.destroyed = False

        self.last_reason = None

    # =================================================
    # Record Trade
    # =================================================

    def record_trade(
        self,
        expected_edge,
        profit,
        probability=None,
        hit=None,
        bankroll=None,
        regime=None,
    ):

        self.expected_edges.append(expected_edge)
        self.real_profits.append(profit)

        if probability is not None:
            self.probabilities.append(probability)

        if hit is not None:
            self.hits.append(hit)

        if bankroll is not None:
            self.bankroll_history.append(bankroll)

        if regime is not None:
            self.regime_history.append(regime)

        # memory cap
        self.expected_edges = self.expected_edges[-500:]
        self.real_profits = self.real_profits[-500:]

        self.probabilities = self.probabilities[-500:]
        self.hits = self.hits[-500:]

        self.bankroll_history = (
            self.bankroll_history[-500:]
        )

        self.regime_history = (
            self.regime_history[-500:]
        )

    # =================================================
    # Brier
    # =================================================

    def brier_score(self):

        if len(self.probabilities) < 30:
            return None

        probs = np.array(self.probabilities)
        hits = np.array(self.hits)

        return np.mean(
            (probs - hits) ** 2
        )

    # =================================================
    # Calibration Collapse
    # =================================================

    def calibration_failure(self):

        if len(self.probabilities) < 100:
            return False

        recent_probs = np.array(
            self.probabilities[-50:]
        )

        recent_hits = np.array(
            self.hits[-50:]
        )

        old_probs = np.array(
            self.probabilities[:50]
        )

        old_hits = np.array(
            self.hits[:50]
        )

        recent_brier = np.mean(
            (recent_probs - recent_hits) ** 2
        )

        old_brier = np.mean(
            (old_probs - old_hits) ** 2
        )

        # 25%以上悪化
        return recent_brier > old_brier * 1.25

    # =================================================
    # Edge Reality Failure
    # =================================================

    def edge_failure(self):

        if len(self.expected_edges) < 80:
            return False

        expected = np.mean(
            self.expected_edges[-80:]
        )

        realized = np.mean(
            self.real_profits[-80:]
        )

        # Edge幻想
        return realized < -abs(expected)

    # =================================================
    # Variance Explosion
    # =================================================

    def variance_explosion(self):

        if len(self.real_profits) < 100:
            return False

        recent_std = np.std(
            self.real_profits[-50:]
        )

        overall_std = np.std(
            self.real_profits
        )

        if overall_std == 0:
            return False

        return recent_std > overall_std * 2

    # =================================================
    # Bankroll Collapse
    # =================================================

    def bankroll_instability(self):

        if len(self.bankroll_history) < 50:
            return False

        bankroll = np.array(
            self.bankroll_history
        )

        peak = np.maximum.accumulate(
            bankroll
        )

        dd = 1 - bankroll / peak

        max_dd = np.max(dd)

        # survival limit
        return max_dd > 0.35

    # =================================================
    # Regime Instability
    # =================================================

    def regime_instability(self):

        if len(self.regime_history) < 50:
            return False

        recent = self.regime_history[-20:]

        unique = len(set(recent))

        # regime激変
        return unique >= 3

    # =================================================
    # Final Evaluation
    # =================================================

    def evaluate(self):

        if self.destroyed:
            return False

        # -----------------------------------------
        # Priority Order
        # -----------------------------------------

        if self.bankroll_instability():

            self.destroyed = True

            self.last_reason = (
                "BANKROLL_COLLAPSE"
            )

            return False

        if self.calibration_failure():

            self.destroyed = True

            self.last_reason = (
                "CALIBRATION_COLLAPSE"
            )

            return False

        if self.edge_failure():

            self.destroyed = True

            self.last_reason = (
                "EDGE_ILLUSION"
            )

            return False

        if self.variance_explosion():

            self.destroyed = True

            self.last_reason = (
                "VARIANCE_EXPLOSION"
            )

            return False

        if self.regime_instability():

            self.destroyed = True

            self.last_reason = (
                "REGIME_INSTABILITY"
            )

            return False

        return True

    # =================================================
    # Status
    # =================================================

    def status(self):

        return {
            "strategy_alive": (
                not self.destroyed
            ),

            "destroyed": self.destroyed,

            "reason": self.last_reason,

            "brier": self.brier_score(),

            "trades": len(
                self.real_profits
            ),
        }

    # =================================================
    # Manual Reset
    # =================================================

    def reset(self):

        self.destroyed = False
        self.last_reason = None