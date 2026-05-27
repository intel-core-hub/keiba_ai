# research/future/future_engine.py

import math
import random

from copy import deepcopy
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

from core.world_model import (
    WorldModel
)


class FutureEngine:
    """
    Survival Future Imagination

    目的:
    - future branching
    - counterfactual analysis
    - collapse forecasting
    - adaptive survival planning

    最重要:
    「未来分岐を想像する」
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

        self.world = (
            WorldModel()
        )

        # =================================================
        # future memory
        # =================================================

        self.scenarios = []

        self.future_tree = {}

        self.last_projection = None

        # =================================================
        # limits
        # =================================================

        self.max_depth = 6

        self.branch_factor = 3

        self.max_scenarios = 1000

    # =================================================
    # Generate Futures
    # =================================================

    def generate_futures(

        self,

        current_world,
        depth=3,
    ):

        self.scenarios = []

        root = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "depth":
                0,

            "state":
                deepcopy(
                    current_world
                ),

            "probability":
                1.0,

            "path":
                [],

            "children":
                [],
        }

        self.expand_node(

            node=root,

            depth=depth,
        )

        self.future_tree = root

        self.last_projection = (
            datetime.utcnow()
            .isoformat()
        )

        # =================================================
        # persistence
        # =================================================

        self.db.save_snapshot(

            state_type="FUTURE_TREE",

            payload={
                "generated":
                    self.last_projection,

                "scenarios":
                    len(
                        self.scenarios
                    ),
            },
        )

        self.audit.log(

            category="FUTURE_ENGINE",

            action="GENERATE",

            severity="INFO",

            metadata={
                "scenario_count":
                    len(
                        self.scenarios
                    )
            },
        )

        return self.scenarios

    # =================================================
    # Expand Node
    # =================================================

    def expand_node(

        self,

        node,
        depth,
    ):

        if depth <= 0:
            return

        if len(self.scenarios) >= (
            self.max_scenarios
        ):
            return

        children = []

        for branch in range(
            self.branch_factor
        ):

            child_state = (
                self.simulate_next_state(
                    deepcopy(
                        node["state"]
                    ),
                    branch,
                )
            )

            probability = (
                self.estimate_probability(
                    child_state
                )
            )

            scenario = {

                "timestamp":
                    datetime.utcnow()
                    .isoformat(),

                "depth":
                    node["depth"] + 1,

                "state":
                    child_state,

                "probability":
                    probability,

                "path":
                    node["path"] + [
                        child_state[
                            "regime"
                        ]
                    ],

                "children":
                    [],
            }

            children.append(
                scenario
            )

            self.scenarios.append(
                scenario
            )

            self.expand_node(

                node=scenario,

                depth=depth - 1,
            )

        node["children"] = children

    # =================================================
    # Simulate State
    # =================================================

    def simulate_next_state(

        self,

        state,
        branch_id,
    ):

        volatility = state.get(
            "market_volatility",
            0.1,
        )

        collapse = state.get(
            "collapse_probability",
            0.1,
        )

        stress = state.get(
            "stress_index",
            0.1,
        )

        sentiment = state.get(
            "sentiment_score",
            0.0,
        )

        # =================================================
        # branch behaviors
        # =================================================

        if branch_id == 0:

            # =============================================
            # stabilization
            # =============================================

            volatility *= (
                random.uniform(
                    0.7,
                    0.95
                )
            )

            stress *= (
                random.uniform(
                    0.7,
                    0.9
                )
            )

            collapse *= (
                random.uniform(
                    0.5,
                    0.9
                )
            )

            sentiment += (
                random.uniform(
                    0.05,
                    0.2
                )
            )

        elif branch_id == 1:

            # =============================================
            # volatile continuation
            # =============================================

            volatility *= (
                random.uniform(
                    0.95,
                    1.25
                )
            )

            stress *= (
                random.uniform(
                    0.95,
                    1.20
                )
            )

            collapse *= (
                random.uniform(
                    0.9,
                    1.2
                )
            )

            sentiment += (
                random.uniform(
                    -0.1,
                    0.1
                )
            )

        else:

            # =============================================
            # crisis escalation
            # =============================================

            volatility *= (
                random.uniform(
                    1.2,
                    1.8
                )
            )

            stress *= (
                random.uniform(
                    1.2,
                    1.7
                )
            )

            collapse *= (
                random.uniform(
                    1.2,
                    1.8
                )
            )

            sentiment -= (
                random.uniform(
                    0.1,
                    0.4
                )
            )

        # =================================================
        # clamp
        # =================================================

        volatility = min(
            1.0,
            max(0.0, volatility)
        )

        stress = min(
            1.0,
            max(0.0, stress)
        )

        collapse = min(
            1.0,
            max(0.0, collapse)
        )

        sentiment = min(
            1.0,
            max(-1.0, sentiment)
        )

        regime = self.classify_regime(

            volatility=
                volatility,

            stress=
                stress,

            collapse=
                collapse,

            sentiment=
                sentiment,
        )

        return {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "market_volatility":
                volatility,

            "stress_index":
                stress,

            "collapse_probability":
                collapse,

            "sentiment_score":
                sentiment,

            "regime":
                regime,
        }
