# simulation/live_simulation.py
# regime detector 統合版

import logging
import time

import numpy as np
import pandas as pd

from datetime import datetime

from core.prediction.predictor import (
    Predictor
)

from core.prediction.regime_detector import (
    RegimeDetector
)

from core.execution.bet_executor import (
    BetExecutor
)

from core.portfolio_allocator import (
    PortfolioAllocator
)

try:
    from core.cognition.meta_controller import (
        MetaController
    )
except Exception:
    class MetaController:
        def decide(self, *args, **kwargs):
            return {"mode": "NORMAL", "reason": "meta_controller_unavailable"}

from core.security.emergency_shutdown import (
    SelfDestructSystem
)

from learning.brier_score import (
    BrierMonitor
)

from learning.performance_analyzer import (
    PerformanceAnalyzer
)


logger = logging.getLogger(__name__)


class _RiskSnapshotProxy:
    def __init__(self):
        self._bankroll = 0.0

    def set_bankroll(self, bankroll):
        self._bankroll = float(bankroll)

    def status(self):
        return {
            "bankroll": self._bankroll,
            "drawdown": 0.0,
            "risk_multiplier": 1.0,
            "lose_streak": 0,
            "win_streak": 0,
            "race_risk_used": 0.0,
        }


class DecisionLoggerAdapter:
    def __init__(self):
        self._risk_proxy = _RiskSnapshotProxy()
        self._executor = BetExecutor(risk_manager=self._risk_proxy)

    def set_bankroll(self, bankroll):
        self._risk_proxy.set_bankroll(bankroll)

    def log_skip(self, **kwargs):
        return None

    def log_decision(self, **kwargs):
        class _Decision:
            pass

        d = _Decision()
        d.race_id = kwargs.get("race_id", "UNKNOWN")
        d.selection = kwargs.get("selection", "UNKNOWN")
        d.probability = float(kwargs.get("probability", 0.0))
        d.odds = float(kwargs.get("odds", 1.0))
        d.edge = float(kwargs.get("edge", 0.0))
        d.bet_size = float(kwargs.get("final_size", 0.0))

        self._executor.execute_bet(d)

    def log_outcome(self, **kwargs):
        class _Decision:
            pass

        d = _Decision()
        d.race_id = kwargs.get("race_id", "UNKNOWN")
        d.selection = kwargs.get("selection", "UNKNOWN")
        self._executor.update_result(
            decision=d,
            hit=int(kwargs.get("hit", 0)),
            profit=float(kwargs.get("profit", 0.0)),
        )


class CapitalAllocatorAdapter:
    def __init__(self):
        self._allocator = PortfolioAllocator()

    def allocate(self, bankroll, edge, probability, odds):
        if bankroll <= 0 or edge <= 0:
            return 0.0

        base_fraction = min(max(edge * 0.5, 0.0), 0.03)
        confidence = min(max(probability, 0.0), 1.0)
        odds_penalty = 1.0 / max(1.0, np.log1p(max(odds, 1.0)))
        stake = bankroll * base_fraction * confidence * odds_penalty
        return max(0.0, stake)


class SurvivalGuardAdapter:
    def __init__(self):
        self._guard = SelfDestructSystem()

    def allow_trade(self, bankroll, stake):
        if self._guard.destroyed:
            return False
        if bankroll <= 0:
            return False
        if stake <= 0:
            return False
        if stake > bankroll * 0.1:
            return False
        return True


class LiveSimulation:
    """
    Adaptive Survival Simulation

    目的:
    - regime適応
    - 生存性強化
    - calibration drift対応
    - defensive transition

    最重要:
    「環境変化に適応する」
    """

    def __init__(

        self,

        bankroll=100000,

        min_edge=0.03,

        max_risk=0.02,
    ):

        # =================================================
        # capital
        # =================================================

        self.initial_bankroll = (
            bankroll
        )

        self.bankroll = bankroll

        self.peak_bankroll = bankroll

        # =================================================
        # base controls
        # =================================================

        self.base_min_edge = (
            min_edge
        )

        self.base_max_risk = (
            max_risk
        )

        # adaptive values
        self.current_min_edge = (
            min_edge
        )

        self.current_max_risk = (
            max_risk
        )

        # =================================================
        # systems
        # =================================================

        self.predictor = Predictor()

        self.regime_detector = (
            RegimeDetector()
        )

        self.logger = (
            DecisionLoggerAdapter()
        )

        self.capital_allocator = (
            CapitalAllocatorAdapter()
        )

        self.meta_controller = (
            MetaController()
        )

        self.survival_guard = (
            SurvivalGuardAdapter()
        )

        self.brier_monitor = (
            BrierMonitor()
        )

        self.performance = (
            PerformanceAnalyzer()
        )

        # =================================================
        # state
        # =================================================

        self.trade_count = 0

        self.skip_count = 0

        self.shutdown = False

    @staticmethod
    def _row_to_mapping(row):
        if isinstance(row, dict):
            return row
        if hasattr(row, "_asdict"):
            return row._asdict()
        if hasattr(row, "to_dict"):
            return row.to_dict()
        return dict(row)

        self.current_regime = (
            "WARMUP"
        )

        # =================================================
        # history
        # =================================================

        self.equity_curve = []

    # =================================================
    # Regime Adaptation
    # =================================================

    def adapt_to_regime(
        self,
    ):

        regime = (
            self.regime_detector
            .detect()
        )

        self.current_regime = (
            regime
        )

        risk_scale = (
            self.regime_detector
            .recommended_risk()
        )

        # =================================================
        # adaptive controls
        # =================================================

        self.current_max_risk = (

            self.base_max_risk
            * risk_scale
        )

        # defensive edge widening
        if regime in [

            "VOLATILE",

            "DRIFT",

            "WEAK_EDGE",
        ]:

            self.current_min_edge = (

                self.base_min_edge
                * 1.5
            )

        else:

            self.current_min_edge = (
                self.base_min_edge
            )

        # =================================================
        # shutdown states
        # =================================================

        if not (

            self.regime_detector
            .trading_allowed()
        ):

            logger.warning("[TRADING BLOCKED] regime=%s", regime)

    # =================================================
    # Simulate Race
    # =================================================

    def simulate_race(
        self,
        row,
    ):

        if self.shutdown:
            return None

        # =================================================
        # adaptive regime update
        # =================================================

        self.adapt_to_regime()

        # =================================================
        # no trading regime
        # =================================================

        if not (

            self.regime_detector
            .trading_allowed()
        ):

            self.skip_count += 1

            return None

        # =================================================
        # features
        # =================================================

        row_data = self._row_to_mapping(row)
        features = dict(row_data)

        race_id = row_data.get(
            "race_id",
            "UNKNOWN",
        )

        horse = row_data.get(
            "horse_name",
            "UNKNOWN",
        )

        odds = float(
            row_data.get(
                "odds",
                1,
            )
        )

        # =================================================
        # predict
        # =================================================

        probability = (
            self.predictor.predict(

                race_id=race_id,

                selection=horse,

                features=features,

                odds=odds,
            )
        )

        implied_prob = (
            1 / odds
        )

        edge = (
            probability
            - implied_prob
        )

        # =================================================
        # adaptive skip
        # =================================================

        if edge < self.current_min_edge:

            self.skip_count += 1

            self.logger.log_skip(

                race_id=race_id,

                selection=horse,

                reason=(
                    f"LOW_EDGE_"
                    f"{self.current_regime}"
                ),

                probability=(
                    probability
                ),

                odds=odds,

                edge=edge,
            )

            return None

        # =================================================
        # capital allocation
        # =================================================

        stake = (
            self.capital_allocator
            .allocate(

                bankroll=(
                    self.bankroll
                ),

                edge=edge,

                probability=(
                    probability
                ),

                odds=odds,
            )
        )

        # =================================================
        # adaptive risk clipping
        # =================================================

        max_allowed = (

            self.bankroll
            * self.current_max_risk
        )

        stake = min(
            stake,
            max_allowed,
        )

        # =================================================
        # survival guard
        # =================================================

        allowed = (
            self.survival_guard
            .allow_trade(

                bankroll=(
                    self.bankroll
                ),

                stake=stake,
            )
        )

        if not allowed:

            self.skip_count += 1

            return None

        # =================================================
        # execute
        # =================================================

        self.trade_count += 1

        self.logger.set_bankroll(self.bankroll)

        hit = int(
            row_data.get(
                "target_win",
                0,
            )
        )

        if hit == 1:

            profit = (
                stake
                * (odds - 1)
            )

        else:

            profit = -stake

        # =================================================
        # bankroll update
        # =================================================

        self.bankroll += profit

        self.peak_bankroll = max(

            self.peak_bankroll,

            self.bankroll,
        )

        drawdown = (

            self.peak_bankroll
            - self.bankroll

        ) / max(
            self.peak_bankroll,
            1,
        )

        # =================================================
        # monitoring
        # =================================================

        self.performance.record(
            profit
        )

        self.brier_monitor.record(

            probability=(
                probability
            ),

            hit=hit,

            odds=odds,
        )

        # =================================================
        # regime learning
        # =================================================

        self.regime_detector.record(

            profit=profit,

            probability=(
                probability
            ),

            outcome=hit,

            edge=edge,
        )

        # =================================================
        # equity
        # =================================================

        self.equity_curve.append(
            self.bankroll
        )

        # =================================================
        # logs
        # =================================================

        self.logger.log_decision(

            race_id=race_id,

            selection=horse,

            probability=(
                probability
            ),

            odds=odds,

            edge=edge,

            decision="BET",

            bankroll=(
                self.bankroll
            ),

            final_size=stake,

            regime=(
                self.current_regime
            ),
        )

        self.logger.log_outcome(

            race_id=race_id,

            selection=horse,

            hit=hit,

            profit=profit,

            bankroll_after=(
                self.bankroll
            ),

            drawdown=drawdown,

            survival_score=(
                self.survival_score()
            ),
        )

        # =================================================
        # danger detection
        # =================================================

        self.detect_danger(
            drawdown
        )

        return {

            "race_id":
                race_id,

            "horse":
                horse,

            "regime":
                self.current_regime,

            "signal":
                (
                    self.regime_detector
                    .survival_signal()
                ),

            "probability":
                round(
                    probability,
                    4,
                ),

            "edge":
                round(
                    edge,
                    4,
                ),

            "stake":
                round(
                    stake,
                    2,
                ),

            "profit":
                round(
                    profit,
                    2,
                ),

            "bankroll":
                round(
                    self.bankroll,
                    2,
                ),
        }

    # =================================================
    # Danger Detection
    # =================================================

    def detect_danger(
        self,
        drawdown,
    ):

        regime = (
            self.current_regime
        )

        # =================================================
        # hard shutdown
        # =================================================

        if regime == "COLLAPSE":

            self.shutdown = True

            logger.critical("[EMERGENCY SHUTDOWN] REGIME COLLAPSE")

            return

        # =================================================
        # drawdown shutdown
        # =================================================

        if drawdown > 0.4:

            self.shutdown = True

            logger.critical("[SHUTDOWN] MAX DRAWDOWN")

    # =================================================
    # Survival Score
    # =================================================

    def survival_score(
        self,
    ):

        if self.trade_count == 0:
            return 1.0

        perf = (
            self.performance.summary()
        )

        drawdown = perf.get(
            "max_drawdown",
            1,
        )

        brier = (
            self.brier_monitor
            .current_brier()
        )

        regime_penalty = 1.0

        if self.current_regime in [

            "VOLATILE",

            "WEAK_EDGE",
        ]:

            regime_penalty = 0.8

        elif self.current_regime in [

            "DRIFT",

            "COLLAPSE",
        ]:

            regime_penalty = 0.5

        score = np.mean([

            1 - min(drawdown, 1),

            1 - min(brier, 1),

            min(
                self.bankroll
                / self.initial_bankroll,

                2,
            ) / 2,
        ])

        score *= regime_penalty

        return round(
            score,
            6,
        )

    # =================================================
    # Run
    # =================================================

    def run(
        self,
        dataframe,
    ):

        logger.info("====================")
        logger.info("ADAPTIVE LIVE SIM")
        logger.info("====================")

        if "race_date" in dataframe:

            dataframe = (
                dataframe
                .sort_values(
                    "race_date"
                )
                .reset_index(
                    drop=True
                )
            )

        for idx, row in enumerate(dataframe.itertuples(index=False, name="RaceRow")):

            if self.shutdown:
                break

            result = (
                self.simulate_race(
                    row
                )
            )

            if result:

                logger.info("%s", result)

            # periodic diagnostics
            if idx % 100 == 0:

                logger.info("[DIAGNOSTICS]")

                logger.info("%s", self.summary())

                logger.info("%s", self.regime_detector.diagnostics())

        logger.info("====================")
        logger.info("SIM COMPLETE")
        logger.info("====================")

        return self.summary()

    # =================================================
    # Summary
    # =================================================

    def summary(
        self,
    ):

        roi = (

            self.bankroll
            - self.initial_bankroll

        ) / max(
            self.initial_bankroll,
            1,
        )

        return {

            "bankroll":
                round(
                    self.bankroll,
                    2,
                ),

            "roi":
                round(
                    roi,
                    6,
                ),

            "trades":
                self.trade_count,

            "skips":
                self.skip_count,

            "regime":
                self.current_regime,

            "survival_score":
                self.survival_score(),

            "risk_limit":
                round(
                    self.current_max_risk,
                    6,
                ),

            "edge_threshold":
                round(
                    self.current_min_edge,
                    6,
                ),

            "shutdown":
                self.shutdown,
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    try:

        df = pd.read_csv(
            "data/processed/historical_dataset.csv"
        )

        sim = LiveSimulation(

            bankroll=100000,

            min_edge=0.03,

            max_risk=0.02,
        )

        result = sim.run(df)

        logger.info("FINAL")

        logger.info("%s", result)

    except Exception as e:

        logger.exception("[SIM ERROR] %s", e)