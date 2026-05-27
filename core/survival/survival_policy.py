# core/survival_policy.py

import math
import statistics

from datetime import datetime

from infrastructure.database import (
    SurvivalDatabase
)

from core.audit_logger import (
    AuditLogger
)

from core.alert_manager import (
    AlertManager
)


class SurvivalPolicy:
    """
    Principle-Driven Survival Intelligence

    目的:
    - long-term survival scoring
    - existential risk minimization
    - resilience optimization
    - anti-fragility evaluation

    最重要:
    「どの未来を選ぶべきか」
    """

    def __init__(
        self,
    ):

        # =================================================
        # infrastructure
        # =================================================

        self.db = (
            SurvivalDatabase()
        )

        self.audit = (
            AuditLogger()
        )

        self.alerts = (
            AlertManager()
        )

        # =================================================
        # policy weights
        # =================================================

        self.weights = {

            # survival continuity
            "survival":
                0.30,

            # collapse avoidance
            "collapse":
                0.25,

            # adaptability
            "adaptation":
                0.15,

            # resilience
            "resilience":
                0.15,

            # redundancy
            "redundancy":
                0.10,

            # anti-fragility
            "antifragility":
                0.05,
        }

        # =================================================
        # thresholds
        # =================================================

        self.minimum_survival_score = (
            0.40
        )

        self.maximum_collapse_risk = (
            0.80
        )

        self.minimum_resilience = (
            0.30
        )

        # =================================================
        # memory
        # =================================================

        self.policy_history = []

        self.last_decision = None

    # =================================================
    # Evaluate Scenario
    # =================================================

    def evaluate_scenario(

        self,

        scenario,
    ):

        state = scenario.get(
            "state",
            {}
        )

        # =================================================
        # extract metrics
        # =================================================

        collapse_probability = (
            state.get(
                "collapse_probability",
                0.0
            )
        )

        stress_index = (
            state.get(
                "stress_index",
                0.0
            )
        )

        volatility = (
            state.get(
                "market_volatility",
                0.0
            )
        )

        sentiment = abs(
            state.get(
                "sentiment_score",
                0.0
            )
        )

        probability = (
            scenario.get(
                "probability",
                0.0
            )
        )

        # =================================================
        # survival continuity
        # =================================================

        survival_score = (
            1.0 -
            collapse_probability
        )

        # =================================================
        # collapse avoidance
        # =================================================

        collapse_avoidance = (
            1.0 -
            collapse_probability
        )

        # =================================================
        # adaptation capability
        # =================================================

        adaptation_score = max(

            0.0,

            min(
                1.0,

                1.0 -
                abs(
                    volatility - 0.5
                )
            )
        )

        # =================================================
        # resilience
        # =================================================

        resilience_score = (

            1.0 -
            stress_index
        )

        # =================================================
        # redundancy preference
        # =================================================

        redundancy_score = (

            1.0 -
            sentiment
        )

        # =================================================
        # anti-fragility
        # =================================================

        antifragility_score = (

            volatility *
            (1.0 - collapse_probability)
        )

        # =================================================
        # weighted policy score
        # =================================================

        policy_score = (

            survival_score
            * self.weights[
                "survival"
            ]

            +

            collapse_avoidance
            * self.weights[
                "collapse"
            ]

            +

            adaptation_score
            * self.weights[
                "adaptation"
            ]

            +

            resilience_score
            * self.weights[
                "resilience"
            ]

            +

            redundancy_score
            * self.weights[
                "redundancy"
            ]

            +

            antifragility_score
            * self.weights[
                "antifragility"
            ]
        )

        result = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "policy_score":
                round(
                    policy_score,
                    4
                ),

            "survival_score":
                round(
                    survival_score,
                    4
                ),

            "collapse_avoidance":
                round(
                    collapse_avoidance,
                    4
                ),

            "adaptation_score":
                round(
                    adaptation_score,
                    4
                ),

            "resilience_score":
                round(
                    resilience_score,
                    4
                ),

            "redundancy_score":
                round(
                    redundancy_score,
                    4
                ),

            "antifragility_score":
                round(
                    antifragility_score,
                    4
                ),

            "scenario_probability":
                probability,

            "approved":
                self.approve(
                    policy_score,
                    collapse_probability,
                    resilience_score,
                ),
        }

        self.last_decision = (
            result
        )

        self.policy_history.append(
            result
        )

        self.policy_history = (
            self.policy_history[-1000:]
        )

        # =================================================
        # persistence
        # =================================================

        self.db.save_snapshot(

            state_type=
                "SURVIVAL_POLICY",

            payload=result,
        )

        # =================================================
        # audit
        # =================================================

        self.audit.log(

            category=
                "SURVIVAL_POLICY",

            action=
                "EVALUATE",

            severity="INFO",

            metadata=result,
        )

        return result

    # =================================================
    # Approve / Reject
    # =================================================

    def approve(

        self,

        policy_score,
        collapse_probability,
        resilience_score,
    ):

        if (
            collapse_probability >
            self.maximum_collapse_risk
        ):

            return False

        if (
            resilience_score <
            self.minimum_resilience
        ):

            return False

        if (
            policy_score <
            self.minimum_survival_score
        ):

            return False

        return True

    # =================================================
    # Rank Futures
    # =================================================

    def rank_futures(

        self,

        scenarios,
    ):

        ranked = []

        for scenario in scenarios:

            evaluation = (
                self.evaluate_scenario(
                    scenario
                )
            )

            ranked.append({

                "scenario":
                    scenario,

                "evaluation":
                    evaluation,
            })

        ranked.sort(

            key=lambda x:
                x["evaluation"][
                    "policy_score"
                ],

            reverse=True,
        )

        return ranked

    # =================================================
    # Select Best Future
    # =================================================

    def select_best_future(

        self,

        scenarios,
    ):

        ranked = (
            self.rank_futures(
                scenarios
            )
        )

        if not ranked:
            return None

        best = ranked[0]

        # =================================================
        # alert if no viable futures
        # =================================================

        if not best[
            "evaluation"
        ][
            "approved"
        ]:

            self.alerts.emit(

                level="CRITICAL",

                title=(
                    "NO VIABLE FUTURE"
                ),

                message=(
                    "all futures below "
                    "survival threshold"
                ),
            )

        return best

    # =================================================
    # Civilization Stability
    # =================================================

    def civilization_stability(
        self,
    ):

        if not self.policy_history:
            return 0.0

        scores = [

            p["policy_score"]

            for p in (
                self.policy_history
            )
        ]

        return round(

            statistics.mean(scores),

            4
        )

    # =================================================
    # Policy Drift
    # =================================================

    def policy_drift(
        self,
    ):

        if len(
            self.policy_history
        ) < 2:

            return 0.0

        scores = [

            p["policy_score"]

            for p in (
                self.policy_history
            )
        ]

        drift = abs(

            scores[-1]
            -
            statistics.mean(scores)
        )

        return round(
            drift,
            4
        )

    # =================================================
    # Recommendations
    # =================================================

    def recommendations(
        self,
    ):

        recommendations = []

        stability = (
            self.civilization_stability()
        )

        drift = (
            self.policy_drift()
        )

        if stability < 0.4:

            recommendations.append(
                "REDUCE_SYSTEMIC_RISK"
            )

        if drift > 0.3:

            recommendations.append(
                "STABILIZE_POLICY"
            )

        if stability > 0.75:

            recommendations.append(
                "CONTROLLED_EXPANSION"
            )

        if not recommendations:

            recommendations.append(
                "MAINTAIN_RESILIENCE"
            )

        return recommendations

    # =================================================
    # Summary
    # =================================================

    def summary(
        self,
    ):

        return {

            "evaluations":
                len(
                    self.policy_history
                ),

            "civilization_stability":
                self
                .civilization_stability(),

            "policy_drift":
                self
                .policy_drift(),

            "last_decision":
                self.last_decision,
        }

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "summary":
                self.summary(),

            "recommendations":
                self.recommendations(),

            "weights":
                self.weights,
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    policy = (
        SurvivalPolicy()
    )

    scenario = {

        "probability":
            0.73,

        "state": {

            "collapse_probability":
                0.18,

            "stress_index":
                0.32,

            "market_volatility":
                0.41,

            "sentiment_score":
                0.12,

            "regime":
                "STABLE",
        }
    }

    result = (
        policy.evaluate_scenario(
            scenario
        )
    )

    print(result)

    ranked = (
        policy.rank_futures([
            scenario
        ])
    )

    print(ranked)

    print(
        policy.summary()
    )

    print(
        policy.recommendations()
    )

    print(
        policy.diagnostics()
    )