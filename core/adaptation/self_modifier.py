# core/self_modifier.py

import copy
import json
import random

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

from core.survival_policy import (
    SurvivalPolicy
)


class SelfModifier:
    """
    Recursive Self-Evolution Layer

    目的:
    - adaptive mutation
    - autonomous tuning
    - resilience evolution
    - recursive self-improvement

    最重要:
    「自分自身を進化させる」
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

        self.policy = (
            SurvivalPolicy()
        )

        # =================================================
        # mutable configuration
        # =================================================

        self.config = {

            "risk_tolerance":
                0.50,

            "adaptation_rate":
                0.15,

            "mutation_rate":
                0.10,

            "redundancy_factor":
                2,

            "recovery_bias":
                0.60,

            "exploration_bias":
                0.40,

            "stress_limit":
                0.75,

            "collapse_limit":
                0.80,
        }

        # =================================================
        # evolution memory
        # =================================================

        self.mutation_history = []

        self.evolution_history = []

        self.last_mutation = None

        # =================================================
        # evolution limits
        # =================================================

        self.max_mutations = 10000

        self.safe_mode = True

    # =================================================
    # Mutate
    # =================================================

    def mutate(
        self,
    ):

        mutated = copy.deepcopy(
            self.config
        )

        mutation_record = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "changes":
                {},
        }

        # =================================================
        # apply parameter mutations
        # =================================================

        for key, value in (
            mutated.items()
        ):

            if random.random() < (
                self.config[
                    "mutation_rate"
                ]
            ):

                delta = random.uniform(
                    -0.15,
                    0.15
                )

                if isinstance(
                    value,
                    int
                ):

                    new_value = max(
                        1,
                        int(
                            value + delta
                        )
                    )

                else:

                    new_value = max(
                        0.01,
                        min(
                            1.0,
                            value + delta
                        )
                    )

                mutation_record[
                    "changes"
                ][key] = {

                    "old":
                        value,

                    "new":
                        new_value,
                }

                mutated[key] = (
                    new_value
                )

        mutation_record[
            "mutated_config"
        ] = mutated

        self.last_mutation = (
            mutation_record
        )

        self.mutation_history.append(
            mutation_record
        )

        self.mutation_history = (
            self.mutation_history[
                -1000:
            ]
        )

        return mutated

    # =================================================
    # Evaluate Mutation
    # =================================================

    def evaluate_mutation(

        self,

        mutated_config,
        scenario,
    ):

        state = scenario.get(
            "state",
            {}
        )

        collapse = state.get(
            "collapse_probability",
            0.0
        )

        stress = state.get(
            "stress_index",
            0.0
        )

        volatility = state.get(
            "market_volatility",
            0.0
        )

        # =================================================
        # compute survival utility
        # =================================================

        utility = (

            (1.0 - collapse)
            * mutated_config[
                "risk_tolerance"
            ]

            +

            (1.0 - stress)
            * mutated_config[
                "recovery_bias"
            ]

            +

            volatility
            * mutated_config[
                "exploration_bias"
            ]
        )

        # =================================================
        # resilience bonus
        # =================================================

        utility += (

            mutated_config[
                "redundancy_factor"
            ]
            * 0.05
        )

        utility = round(
            utility,
            4
        )

        approved = (
            utility >
            0.50
        )

        result = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "utility":
                utility,

            "approved":
                approved,

            "config":
                mutated_config,
        }

        return result

    # =================================================
    # Evolve
    # =================================================

    def evolve(

        self,

        scenario,
        iterations=10,
    ):

        best_config = (
            self.config
        )

        best_score = -1.0

        evolution_results = []

        for _ in range(
            iterations
        ):

            mutated = (
                self.mutate()
            )

            evaluation = (
                self.evaluate_mutation(

                    mutated_config=
                        mutated,

                    scenario=
                        scenario,
                )
            )

            evolution_results.append(
                evaluation
            )

            if evaluation[
                "utility"
            ] > best_score:

                best_score = (
                    evaluation[
                        "utility"
                    ]
                )

                best_config = (
                    mutated
                )

        # =================================================
        # safe mode protection
        # =================================================

        if self.safe_mode:

            collapse_limit = (
                best_config[
                    "collapse_limit"
                ]
            )

            if collapse_limit > 0.95:

                self.alerts.emit(

                    level="WARNING",

                    title=(
                        "UNSAFE MUTATION"
                    ),

                    message=(
                        "mutation exceeded "
                        "safe collapse limit"
                    ),
                )

                return None

        # =================================================
        # apply evolution
        # =================================================

        self.config = best_config

        evolution_record = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "best_score":
                best_score,

            "config":
                best_config,
        }

        self.evolution_history.append(
            evolution_record
        )

        self.evolution_history = (
            self.evolution_history[
                -1000:
            ]
        )

        # =================================================
        # persistence
        # =================================================

        self.db.save_snapshot(

            state_type=
                "SELF_MODIFIER",

            payload=evolution_record,
        )

        # =================================================
        # audit
        # =================================================

        self.audit.log(

            category=
                "SELF_MODIFIER",

            action=
                "EVOLVE",

            severity="WARNING",

            metadata=evolution_record,
        )

        return evolution_record

    # =================================================
    # Rollback
    # =================================================

    def rollback(
        self,
    ):

        if len(
            self.evolution_history
        ) < 2:

            return False

        previous = (
            self.evolution_history[
                -2
            ]
        )

        self.config = previous[
            "config"
        ]

        self.audit.log(

            category=
                "SELF_MODIFIER",

            action=
                "ROLLBACK",

            severity="ERROR",

            metadata={
                "restored":
                    previous[
                        "timestamp"
                    ]
            },
        )

        return True

    # =================================================
    # Adapt Thresholds
    # =================================================

    def adapt_thresholds(

        self,

        stress_level,
    ):

        if stress_level > 0.7:

            self.config[
                "risk_tolerance"
            ] *= 0.9

            self.config[
                "recovery_bias"
            ] *= 1.1

        elif stress_level < 0.3:

            self.config[
                "exploration_bias"
            ] *= 1.1

        # =================================================
        # clamp
        # =================================================

        for key, value in (
            self.config.items()
        ):

            if isinstance(
                value,
                float
            ):

                self.config[key] = max(

                    0.01,

                    min(1.0, value)
                )

    # =================================================
    # Export Configuration
    # =================================================

    def export_config(
        self,
    ):

        payload = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "config":
                self.config,
        }

        path = (
            "config/"
            "evolved_config.json"
        )

        with open(

            path,

            "w",

            encoding="utf-8",
        ) as f:

            json.dump(

                payload,

                f,

                indent=2,

                ensure_ascii=False,
            )

        return path

    # =================================================
    # Summary
    # =================================================

    def summary(
        self,
    ):

        return {

            "mutations":
                len(
                    self.mutation_history
                ),

            "evolutions":
                len(
                    self.evolution_history
                ),

            "safe_mode":
                self.safe_mode,

            "config":
                self.config,
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

            "last_mutation":
                self.last_mutation,
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    modifier = (
        SelfModifier()
    )

    scenario = {

        "state": {

            "collapse_probability":
                0.22,

            "stress_index":
                0.35,

            "market_volatility":
                0.48,

            "sentiment_score":
                0.10,
        }
    }

    result = (
        modifier.evolve(

            scenario=
                scenario,

            iterations=20,
        )
    )

    print(result)

    print(
        modifier.summary()
    )

    print(
        modifier.diagnostics()
    )

    path = (
        modifier.export_config()
    )

    print(
        "[EXPORTED]",
        path
    )