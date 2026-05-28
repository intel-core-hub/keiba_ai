# main.py

import os

import numpy as np

from core import (
    Predictor,
    BetSizer,
    BetExecutor,
    RiskManager,
    NoBetFilter,
    RegimeDetector,
    PortfolioAllocator,
    CapitalPreservation,
    SelfDestructSystem,
)

from core.utilities.async_tools import (
    LatestResultCache,
)

ENABLE_RESEARCH = os.getenv("KEIBA_ENABLE_RESEARCH", "0") == "1"


class _NullAIEvaluator:
    pass


class _NullPortfolioManager:
    def __init__(self, *args, **kwargs):
        self._regime = None

    def update_regime(self, *args, **kwargs):
        return None

    def evaluate_strategies(self, *args, **kwargs):
        return None

    def allocate_capital(self, *args, **kwargs):
        return []

    def execute(self, *args, **kwargs):
        return []


class _NullMetaController:
    def determine_state(self, *args, **kwargs):
        return {"mode": "NORMAL", "reason": "research_disabled"}

    def diagnostics(self, *args, **kwargs):
        return {"mode": "NORMAL", "reason": "research_disabled"}


class _NullBrierMonitor:
    def record(self, *args, **kwargs):
        return None

    def current_brier(self):
        return None


class _NullReliabilityCurveAnalyzer:
    def record(self, *args, **kwargs):
        return None

    def recommendation(self):
        return {"status": "disabled", "reason": "research_disabled"}

    def diagnostics(self):
        return {"status": "disabled", "reason": "research_disabled"}


class _NullPerformanceAnalyzer:
    pass


class _NullMonteCarloSurvivalSimulator:
    def __init__(self, *args, **kwargs):
        pass

    def simulate(self, *args, **kwargs):
        return {"status": "disabled", "reason": "research_disabled"}


if ENABLE_RESEARCH:

    from meta.ai_evaluator import (
        AIEvaluator,
    )

    from meta.portfolio_manager import (
        PortfolioManager,
    )

    from learning.brier_score import (
        BrierMonitor,
    )

    from learning.reliability_curve import (
        ReliabilityCurveAnalyzer,
    )

    from learning.performance_analyzer import (
        PerformanceAnalyzer,
    )

    from learning.monte_carlo import (
        MonteCarloSurvivalSimulator,
    )
else:
    MetaController = _NullMetaController
    AIEvaluator = _NullAIEvaluator
    PortfolioManager = _NullPortfolioManager
    BrierMonitor = _NullBrierMonitor
    ReliabilityCurveAnalyzer = _NullReliabilityCurveAnalyzer
    PerformanceAnalyzer = _NullPerformanceAnalyzer
    MonteCarloSurvivalSimulator = _NullMonteCarloSurvivalSimulator

from strategies import (
    WideAI,
    MarketAI,
    ExplorerAI,
)

from core.execution.calibration_refit import CalibrationRefitJob
from core.prediction.feature_precompute import precompute_for_race



# =====================================================
# Decision
# =====================================================

class Decision:

    def __init__(
        self,
        race_id,
        selection,
        probability,
        odds,
        edge,
        bet_size,
    ):

        self.race_id = race_id

        self.selection = selection

        self.probability = probability

        self.odds = odds

        self.edge = edge

        self.bet_size = bet_size


# =====================================================
# Survival OS
# =====================================================

class SurvivalOS:
    """
    Survival Operating System

    思想:
    「予測」
    より
    「生存」

    目的:
    - calibration維持
    - drawdown抑制
    - participation control
    - regime adaptation
    - self destruction prevention
    """

    def __init__(self):

        # =================================================
        # Core
        # =================================================

        self.predictor = Predictor()

        self.risk_manager = RiskManager()

        self.bet_sizer = BetSizer(
            risk_manager=self.risk_manager
        )

        self.calibration_job = CalibrationRefitJob()

        def _on_bet_settled(_row):
            self.calibration_job.record_new_settlement(1)
            self.calibration_job.maybe_refit(
                reliability_analyzer=self.reliability,
            )

        self.executor = BetExecutor(
            risk_manager=self.risk_manager,
            on_settle=_on_bet_settled,
        )

        # =================================================
        # Survival Layers
        # =================================================

        self.no_bet_filter = (
            NoBetFilter()
        )

        self.regime_detector = (
            RegimeDetector()
        )

        self.portfolio_allocator = (
            PortfolioAllocator()
        )

        self.capital = (
            CapitalPreservation(
                initial_capital=(
                    self.risk_manager.bankroll
                )
            )
        )

        self.meta_controller = (
            MetaController()
        )

        self.self_destruct = (
            SelfDestructSystem()
        )

        self.executor.register_emergency_source(
            self.self_destruct
        )

        self.strategies = [
            WideAI(
                predictor=self.predictor,
                bet_sizer=self.bet_sizer,
            ),
            MarketAI(
                predictor=self.predictor,
                bet_sizer=self.bet_sizer,
            ),
            ExplorerAI(
                predictor=self.predictor,
                bet_sizer=self.bet_sizer,
            ),
        ]

        self.portfolio = PortfolioManager(
            strategies=self.strategies,
            evaluator=AIEvaluator(),
            regime=self.regime_detector,
            risk=self.risk_manager,
        )

        # =================================================
        # Monitoring
        # =================================================

        self.brier_monitor = (
            BrierMonitor()
        )

        self.reliability = (
            ReliabilityCurveAnalyzer()
        )

        self.performance = (
            PerformanceAnalyzer()
        )

        # =================================================
        # Simulation
        # =================================================

        self.monte_carlo = (
            MonteCarloSurvivalSimulator(
                initial_bankroll=(
                    self.risk_manager.bankroll
                )
            )
        )

        # =================================================
        # State
        # =================================================

        self.recent_profits = []

        # =================================================
        # Latency Control
        # =================================================

        self.analysis_cache = LatestResultCache(
            max_workers=2,
            ttl_seconds=12.0,
        )

        self._causal_engine = None

        self._future_engine = None

        self._analysis_cache_key = (
            "race_latency_analysis"
        )

    def precompute_race_features(self, race_id: str, rows: list) -> dict:
        """Convenience: compute and cache features for a race using analysis_cache."""
        try:
            return precompute_for_race(race_id, rows, self.analysis_cache)
        except Exception as exc:
            logger = __import__("logging").getLogger(__name__)
            logger.warning("precompute_race_features failed: %s", exc)
            return {}
    
        def _default_latency_snapshot(
            self,
            race_id,
            candidates,
        ):
            return {
                "race_id": race_id,
                "candidate_count": len(candidates),
                "source": "cache_miss",
                "risk_bias": 0.0,
                "confidence_multiplier": 1.0,
                "bet_multiplier": 1.0,
                "halt": False,
                "causal_summary": {},
                "future_summary": {},
            }
    
        def _build_latency_snapshot(
            self,
            race_id,
            candidates,
            meta_state,
            bankroll,
            recent_profits,
        ):
            return self._default_latency_snapshot(
                race_id,
                candidates,
            )
    
        def _apply_latency_snapshot(
            self,
            meta_state,
            snapshot,
        ):
            adjusted = dict(meta_state)
        
            confidence_multiplier = float(
                snapshot.get(
                    "confidence_multiplier",
                    1.0,
                )
            )
            bet_multiplier = float(
                snapshot.get(
                    "bet_multiplier",
                    1.0,
                )
            )
        
            adjusted["confidence_threshold"] = float(
                adjusted.get("confidence_threshold", 0.0)
            ) * confidence_multiplier
            adjusted["bet_multiplier"] = float(
                adjusted.get("bet_multiplier", 1.0)
            ) * bet_multiplier
            adjusted["latency_snapshot"] = snapshot
        
            return adjusted

    # =================================================
    # Process Race
    # =================================================

    def process_race(
        self,
        race_id,
        candidates,
    ):

        # =================================================
        # Global Safety
        # =================================================

        if self.self_destruct.destroyed:

            print(
                "[SYSTEM DESTROYED]"
            )

            return []

        if not self.capital.safe_to_trade():

            print(
                "[CAPITAL LOCKDOWN]"
            )

            return []

        # =================================================
        # Meta State
        # =================================================

        meta_state = (
            self.meta_controller
            .determine_state(

                capital_layer=self.capital,

                reliability_layer=(
                    self.reliability
                ),

                regime_layer=(
                    self.regime_detector
                ),

                lose_streak=(
                    self.risk_manager
                    .lose_streak
                ),
            )
        )

        analysis_snapshot = self.analysis_cache.latest_or_schedule(
            self._analysis_cache_key,
            self._build_latency_snapshot,
            race_id,
            candidates,
            meta_state,
            float(self.risk_manager.bankroll),
            tuple(self.recent_profits),
            default=self._default_latency_snapshot(
                race_id,
                candidates,
            ),
        )

        meta_state = self._apply_latency_snapshot(
            meta_state,
            analysis_snapshot,
        )

        # =================================================
        # Shutdown
        # =================================================

        if (
            meta_state["state"]
            == "SHUTDOWN"
        ):

            print(
                "[META SHUTDOWN]"
            )

            return []

        if analysis_snapshot.get("halt"):

            print(
                "[LATENCY HALT]"
            )

            return []

        # =================================================
        # Candidate Evaluation
        # =================================================

        decisions = []

        for c in candidates:

            selection = c["selection"]

            odds = c["odds"]

            features = c.get(
                "features",
                {},
            )

            # -----------------------------------------
            # prediction
            # -----------------------------------------

            probability = (
                self.predictor.predict(

                    race_id=race_id,

                    selection=selection,

                    features=features,

                    odds=odds,
                )
            )

            # -----------------------------------------
            # edge
            # -----------------------------------------

            market_probability = (
                1 / odds
            )

            edge = (
                probability
                - market_probability
            )

            # -----------------------------------------
            # meta edge threshold
            # -----------------------------------------

            if (
                edge
                < meta_state[
                    "confidence_threshold"
                ]
            ):

                continue

            # -----------------------------------------
            # no bet filter
            # -----------------------------------------

            skip, reason = (
                self.no_bet_filter
                .should_skip(

                    probability=probability,

                    odds=odds,

                    edge=edge,

                    bankroll_status=(
                        self.risk_manager
                        .status()
                    ),

                    brier_status=(
                        self.brier_monitor
                        .current_brier()
                    ),

                    recent_profits=(
                        self.recent_profits
                    ),
                )
            )

            if skip:

                print(
                    f"[SKIP] "
                    f"{selection} "
                    f"{reason}"
                )

                continue

            # -----------------------------------------
            # base sizing
            # -----------------------------------------

            base_size = (
                self.bet_sizer
                .size_bet(

                    probability=(
                        probability
                    ),

                    odds=odds,

                    edge=edge,
                )
            )

            # -----------------------------------------
            # capital preservation
            # -----------------------------------------

            adjusted_size = (
                self.capital
                .adjust_bet_size(
                    base_size
                )
            )

            # -----------------------------------------
            # meta scaling
            # -----------------------------------------

            adjusted_size *= (
                meta_state[
                    "bet_multiplier"
                ]
            )

            # -----------------------------------------
            # minimum size
            # -----------------------------------------

            if adjusted_size < 1:

                continue

            # -----------------------------------------
            # decision
            # -----------------------------------------

            decision = Decision(

                race_id=race_id,

                selection=selection,

                probability=probability,

                odds=odds,

                edge=edge,

                bet_size=adjusted_size,
            )

            decisions.append(
                decision
            )

        # =================================================
        # Portfolio Strategy Layer
        # =================================================

        try:

            race_bundle = [{
                "race_id": race_id,
                "horses": candidates,
                "regime": self.regime_detector.status().get(
                    "regime",
                    self.regime_detector.current_regime,
                ),
            }]

            self.portfolio.update_regime(race_bundle)
            self.portfolio.evaluate_strategies()
            allocations = self.portfolio.allocate_capital()
            strategy_outputs = self.portfolio.execute(race_bundle, allocations)

            for output in strategy_outputs:
                if isinstance(output, Decision):
                    decisions.append(output)
                    continue

                converted = None

                if hasattr(output, "horses"):
                    selection = ",".join(output.horses[0]) if output.horses else "UNKNOWN"
                    converted = Decision(
                        race_id=getattr(output, "race_id", race_id),
                        selection=selection,
                        probability=0.0,
                        odds=1.0,
                        edge=getattr(output, "expected_value", 0.0),
                        bet_size=float(getattr(output, "bet_size", 0.0)),
                    )
                elif hasattr(output, "horse_id") and hasattr(output, "exploration_score"):
                    converted = Decision(
                        race_id=getattr(output, "race_id", race_id),
                        selection=getattr(output, "horse_id", "UNKNOWN"),
                        probability=0.0,
                        odds=float(getattr(output, "odds", 1.0)),
                        edge=float(getattr(output, "exploration_score", 0.0)),
                        bet_size=float(getattr(output, "bet_size", 0.0)),
                    )
                elif hasattr(output, "horse_id"):
                    converted = Decision(
                        race_id=getattr(output, "race_id", race_id),
                        selection=getattr(output, "horse_id", "UNKNOWN"),
                        probability=0.0,
                        odds=1.0,
                        edge=float(getattr(output, "edge", 0.0)),
                        bet_size=float(getattr(output, "bet_size", 0.0)),
                    )

                if converted is not None:
                    decisions.append(converted)

        except Exception as e:
            print("[PORTFOLIO ERROR]", e)

        # =================================================
        # Portfolio Allocation
        # =================================================

        regime = (
            self.regime_detector
            .status()
        )

        allocated = (
            self.portfolio_allocator
            .allocate(

                decisions=decisions,

                bankroll=(
                    self.risk_manager
                    .bankroll
                ),

                regime=(
                    regime["regime"]
                ),
            )
        )

        # =================================================
        # Execute
        # =================================================

        for d in allocated:

            self.executor.execute_bet(
                d
            )

        return allocated

    # =================================================
    # Settle Race
    # =================================================

    def settle_race(
        self,
        decisions,
        winners,
    ):

        race_profit = 0

        edges = []

        odds_list = []

        # =================================================
        # Result Loop
        # =================================================

        for d in decisions:

            hit = (
                d.selection
                in winners
            )

            # -----------------------------------------
            # profit
            # -----------------------------------------

            if hit:

                profit = (
                    d.bet_size
                    * (d.odds - 1)
                )

            else:

                profit = -d.bet_size

            race_profit += profit

            edges.append(d.edge)

            odds_list.append(d.odds)

            # -----------------------------------------
            # update capital
            # -----------------------------------------

            self.risk_manager.update(
                profit
            )

            self.capital.update(
                profit
            )

            # -----------------------------------------
            # logging
            # -----------------------------------------

            self.executor.update_result(

                decision=d,

                hit=hit,

                profit=profit,
            )

            # -----------------------------------------
            # calibration
            # -----------------------------------------

            self.brier_monitor.record(

                probability=(
                    d.probability
                ),

                hit=int(hit),

                odds=d.odds,
            )

            self.reliability.record(

                probability=(
                    d.probability
                ),

                hit=int(hit),
            )

            # -----------------------------------------
            # self destruct
            # -----------------------------------------

            self.self_destruct.record_trade(

                expected_edge=d.edge,

                profit=profit,

                probability=(
                    d.probability
                ),

                hit=int(hit),

                bankroll=(
                    self.risk_manager
                    .bankroll
                ),

                regime=(
                    self.regime_detector
                    .status().get(
                        "regime",
                        self.regime_detector
                        .current_regime
                    )
                ),
            )

            # -----------------------------------------
            # recent profits
            # -----------------------------------------

            self.recent_profits.append(
                profit
            )

            self.recent_profits = (
                self.recent_profits[-500:]
            )

        # =================================================
        # Regime Update
        # =================================================

        if len(odds_list) > 0:

            avg_prob = 0.0
            if len(decisions) > 0:
                avg_prob = float(
                    np.mean(
                        [d.probability for d in decisions]
                    )
                )

            self.regime_detector.record(

                profit=race_profit,

                probability=avg_prob,

                outcome=(
                    1 if race_profit > 0 else 0
                ),

                edge=float(
                    np.mean(edges)
                ),
            )

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(self):

        print("\n==========")
        print("SURVIVAL OS")
        print("==========")

        # -----------------------------------------
        # Meta
        # -----------------------------------------

        print("\n[META]")

        print(
            self.meta_controller
            .diagnostics()
        )

        # -----------------------------------------
        # Capital
        # -----------------------------------------

        print("\n[CAPITAL]")

        print(
            self.capital
            .diagnostics()
        )

        # -----------------------------------------
        # Regime
        # -----------------------------------------

        print("\n[REGIME]")

        print(
            self.regime_detector
            .status()
        )

        # -----------------------------------------
        # Reliability
        # -----------------------------------------

        print("\n[RELIABILITY]")

        print(
            self.reliability
            .recommendation()
        )

        # -----------------------------------------
        # Self Destruct
        # -----------------------------------------

        print("\n[SELF DESTRUCT]")

        print(
            self.self_destruct
            .status()
        )

        # -----------------------------------------
        # Portfolio
        # -----------------------------------------

        print("\n[PORTFOLIO]")
        print("Portfolio diagnostics moved to scripts/admin_portfolio_summary.py (offline).")

    # =================================================
    # Monte Carlo
    # =================================================

    def monte_carlo_check(self):

        print("Monte Carlo diagnostics moved to scripts/admin_portfolio_summary.py (offline).")

            report = (
                self.monte_carlo
                .simulate(

                    probabilities=probs,

                    odds=odds,

                    stakes=stakes,

                    simulations=500,

                    n_bets=300,
                )
            )

            print("\n[MONTE CARLO]")

            print(report)

        except Exception as e:

            print(
                "[MC ERROR]",
                e,
            )


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    system = SurvivalOS()

    race = [

        {
            "selection": "Horse_A",

            "odds": 4.5,

            "features": {

                "rank_score": 0.82,

                "speed_index": 91,

                "odds_value": 0.68,

                "form": 0.79,
            },
        },

        {
            "selection": "Horse_B",

            "odds": 12.0,

            "features": {

                "rank_score": 0.55,

                "speed_index": 76,

                "odds_value": 0.41,

                "form": 0.52,
            },
        },
    ]

    decisions = system.process_race(

        race_id="2026_05_10_TOKYO_11R",

        candidates=race,
    )

    winners = ["Horse_A"]

    system.settle_race(
        decisions,
        winners,
    )

    system.diagnostics()

    system.monte_carlo_check()
