# core/executive_controller.py

from datetime import datetime

from core.regime_detector import (
    RegimeDetector
)

from learning.meta_learner import (
    MetaLearner
)

from learning.strategy_evolver import (
    StrategyEvolver
)

from memory.knowledge_graph import (
    KnowledgeGraph
)

from core.alert_manager import (
    AlertManager
)

from core.audit_logger import (
    AuditLogger
)

from core.state_manager import (
    StateManager
)


class ExecutiveController:
    """
    Integrated Executive Intelligence

    目的:
    - unified decision making
    - strategic orchestration
    - survival prioritization
    - adaptive governance

    最重要:
    「全体を統合判断する」
    """

    def __init__(
        self,
    ):

        # =================================================
        # core systems
        # =================================================

        self.regime_detector = (
            RegimeDetector()
        )

        self.meta_learner = (
            MetaLearner()
        )

        self.evolver = (
            StrategyEvolver()
        )

        self.knowledge_graph = (
            KnowledgeGraph()
        )

        self.alerts = (
            AlertManager()
        )

        self.audit = (
            AuditLogger()
        )

        self.state_manager = (
            StateManager()
        )

        # =================================================
        # executive state
        # =================================================

        self.current_strategy = None

        self.last_decision = None

        self.decision_history = []

        self.shutdown = False

        self.executive_mode = (
            "SURVIVAL"
        )

        # =================================================
        # thresholds
        # =================================================

        self.min_survival_score = (
            0.35
        )

        self.max_risk = 0.70

        self.min_confidence = (
            0.55
        )

    # =================================================
    # Evaluate Environment
    # =================================================

    def evaluate_environment(

        self,

        metrics,
    ):

        regime = (
            self.regime_detector
            .detect(metrics)
        )

        intelligence = (

            self.knowledge_graph
            .survival_intelligence()
        )

        return {

            "regime":
                regime,

            "intelligence":
                intelligence,

            "timestamp":
                datetime.utcnow()
                .isoformat(),
        }

    # =================================================
    # Ask Meta Learner
    # =================================================

    def strategic_recommendation(
        self,
        regime,
    ):

        recommendations = (

            self.meta_learner
            .recommend(
                regime=regime
            )
        )

        if not recommendations:

            return None

        return recommendations[0]

    # =================================================
    # Risk Evaluation
    # =================================================

    def evaluate_risk(

        self,

        survival_score,
        volatility,
        drawdown,
    ):

        risk = 0.0

        # =================================================
        # survival weakness
        # =================================================

        risk += (
            1.0 - survival_score
        ) * 0.5

        # =================================================
        # volatility
        # =================================================

        risk += min(
            volatility,
            1.0,
        ) * 0.3

        # =================================================
        # drawdown
        # =================================================

        risk += min(
            drawdown,
            1.0,
        ) * 0.2

        return min(risk, 1.0)

    # =================================================
    # Executive Decision
    # =================================================

    def decide(

        self,

        metrics,
    ):

        if self.shutdown:

            return {

                "action":
                    "SHUTDOWN",

                "reason":
                    "executive shutdown"
            }

        # =================================================
        # evaluate environment
        # =================================================

        env = (
            self.evaluate_environment(
                metrics
            )
        )

        regime = env["regime"]

        # =================================================
        # metrics
        # =================================================

        survival_score = metrics.get(

            "survival_score",
            0.5,
        )

        volatility = metrics.get(

            "volatility",
            0.5,
        )

        drawdown = metrics.get(

            "drawdown",
            0.0,
        )

        confidence = metrics.get(

            "confidence",
            0.5,
        )

        # =================================================
        # risk
        # =================================================

        risk = self.evaluate_risk(

            survival_score,

            volatility,

            drawdown,
        )

        # =================================================
        # executive logic
        # =================================================

        action = "HOLD"

        reason = "stable"

        # =================================================
        # collapse
        # =================================================

        if regime == "COLLAPSE":

            action = "EMERGENCY_STOP"

            reason = (
                "collapse regime"
            )

            self.alerts.emit(

                level="CRITICAL",

                title="EXECUTIVE STOP",

                message=(
                    "collapse detected"
                ),
            )

        # =================================================
        # excessive risk
        # =================================================

        elif risk > self.max_risk:

            action = "REDUCE_EXPOSURE"

            reason = (
                "risk too high"
            )

        # =================================================
        # low confidence
        # =================================================

        elif confidence < (
            self.min_confidence
        ):

            action = "SKIP"

            reason = (
                "low confidence"
            )

        # =================================================
        # weak survival
        # =================================================

        elif (

            survival_score
            < self.min_survival_score

        ):

            action = "RETRAIN"

            reason = (
                "survival degraded"
            )

        # =================================================
        # favorable
        # =================================================

        elif regime == "FAVORABLE":

            action = "EXPAND"

            reason = (
                "favorable regime"
            )

        # =================================================
        # strategy recommendation
        # =================================================

        recommendation = (

            self.strategic_recommendation(
                regime
            )
        )

        decision = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "regime":
                regime,

            "risk":
                risk,

            "action":
                action,

            "reason":
                reason,

            "recommendation":
                recommendation,

            "metrics":
                metrics,
        }

        # =================================================
        # history
        # =================================================

        self.last_decision = (
            decision
        )

        self.decision_history.append(
            decision
        )

        # =================================================
        # audit
        # =================================================

        self.audit.log(

            category="EXECUTIVE",

            action=action,

            severity=(
                "WARNING"

                if risk > 0.7

                else "INFO"
            ),

            metadata=decision,
        )

        return decision

    # =================================================
    # Learn Outcome
    # =================================================

    def learn_outcome(

        self,

        decision,
        outcome,
    ):

        regime = decision.get(
            "regime",
            "UNKNOWN",
        )

        recommendation = (
            decision.get(
                "recommendation"
            )
        )

        model = "unknown"

        mutation = "unknown"

        if recommendation:

            model = (
                recommendation.get(
                    "model",
                    "unknown",
                )
            )

            mutation = (
                recommendation.get(
                    "mutation",
                    "unknown",
                )
            )

        fitness = outcome.get(
            "fitness",
            0,
        )

        result = outcome.get(
            "result",
            "UNKNOWN",
        )

        # =================================================
        # knowledge graph learning
        # =================================================

        self.knowledge_graph.learn(

            regime=regime,

            model=model,

            mutation=mutation,

            outcome=result,

            fitness=fitness,
        )

        # =================================================
        # meta learning
        # =================================================

        self.meta_learner.record(

            regime=regime,

            model_type=model,

            mutation_type=mutation,

            fitness=fitness,

            survival=(
                outcome.get(
                    "survival",
                    0,
                )
            ),

            accuracy=(
                outcome.get(
                    "accuracy",
                    0,
                )
            ),
        )

        # =================================================
        # persistence
        # =================================================

        self.knowledge_graph.save()

    # =================================================
    # Emergency Shutdown
    # =================================================

    def emergency_shutdown(
        self,
        reason,
    ):

        self.shutdown = True

        self.audit.shutdown(
            reason
        )

        self.alerts.emit(

            level="CRITICAL",

            title="EXECUTIVE SHUTDOWN",

            message=reason,
        )

        return {

            "shutdown":
                True,

            "reason":
                reason,
        }

    # =================================================
    # Restore Operation
    # =================================================

    def restore_operation(
        self,
    ):

        self.shutdown = False

        self.audit.log(

            category="SYSTEM",

            action="RESTORE",

            severity="INFO",
        )

        return {

            "shutdown":
                False
        }

    # =================================================
    # Executive Summary
    # =================================================

    def summary(
        self,
    ):

        return {

            "mode":
                self.executive_mode,

            "shutdown":
                self.shutdown,

            "last_decision":
                self.last_decision,

            "decision_count":
                len(
                    self.decision_history
                ),

            "knowledge":
                (
                    self.knowledge_graph
                    .diagnostics()
                ),

            "meta":
                (
                    self.meta_learner
                    .diagnostics()
                ),
        }

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "executive_mode":
                self.executive_mode,

            "shutdown":
                self.shutdown,

            "history_size":
                len(
                    self.decision_history
                ),

            "thresholds": {

                "min_survival":
                    (
                        self.min_survival_score
                    ),

                "max_risk":
                    self.max_risk,

                "min_confidence":
                    (
                        self.min_confidence
                    ),
            },
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    executive = (
        ExecutiveController()
    )

    metrics = {

        "survival_score":
            0.42,

        "volatility":
            0.71,

        "drawdown":
            0.23,

        "confidence":
            0.58,
    }

    decision = (
        executive.decide(
            metrics
        )
    )

    print("\nDECISION")
    print(decision)

    outcome = {

        "fitness":
            0.73,

        "result":
            "RECOVERY",

        "survival":
            0.81,

        "accuracy":
            0.64,
    }

    executive.learn_outcome(

        decision,

        outcome,
    )

    print("\nSUMMARY")
    print(
        executive.summary()
    )