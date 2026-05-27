# core/causal_engine.py

import math
import statistics

from collections import defaultdict
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


class CausalEngine:
    """
    Causal Survival Intelligence

    目的:
    - cause-effect tracing
    - root failure analysis
    - intervention attribution
    - survival causality mapping

    最重要:
    「なぜ起きたかを理解する」
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
        # causal memory
        # =================================================

        self.events = []

        self.causal_links = []

        self.interventions = []

        self.root_causes = []

        self.last_analysis = None

        # =================================================
        # causal graph
        # =================================================

        self.graph = defaultdict(
            list
        )

        # =================================================
        # thresholds
        # =================================================

        self.minimum_confidence = (
            0.55
        )

        self.maximum_chain_depth = (
            8
        )

    # =================================================
    # Register Event
    # =================================================

    def register_event(

        self,

        event_type,
        payload=None,
        severity=0.5,
    ):

        payload = payload or {}

        event = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "event_type":
                event_type,

            "payload":
                payload,

            "severity":
                severity,
        }

        self.events.append(
            event
        )

        self.events = (
            self.events[-5000:]
        )

        return event

    # =================================================
    # Link Cause and Effect
    # =================================================

    def link_events(

        self,

        cause_event,
        effect_event,
        confidence=0.5,
    ):

        if confidence < (
            self.minimum_confidence
        ):

            return None

        link = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "cause":
                cause_event,

            "effect":
                effect_event,

            "confidence":
                round(
                    confidence,
                    4
                ),
        }

        self.causal_links.append(
            link
        )

        self.graph[
            cause_event[
                "event_type"
            ]
        ].append({

            "effect":
                effect_event[
                    "event_type"
                ],

            "confidence":
                confidence,
        })

        self.audit.log(

            category=
                "CAUSAL_ENGINE",

            action=
                "LINK",

            severity="INFO",

            metadata=link,
        )

        return link

    # =================================================
    # Root Cause Analysis
    # =================================================

    def root_cause_analysis(

        self,

        target_event_type,
    ):

        candidates = []

        # =================================================
        # search backward
        # =================================================

        for link in (
            self.causal_links
        ):

            effect = link[
                "effect"
            ]

            if effect[
                "event_type"
            ] == target_event_type:

                candidates.append({

                    "cause":
                        link["cause"],

                    "confidence":
                        link[
                            "confidence"
                        ],
                })

        # =================================================
        # sort strongest causes
        # =================================================

        candidates.sort(

            key=lambda x:
                x["confidence"],

            reverse=True,
        )

        result = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "target":
                target_event_type,

            "root_causes":
                candidates[
                    :5
                ],
        }

        self.root_causes.append(
            result
        )

        self.last_analysis = (
            result
        )

        # =================================================
        # persistence
        # =================================================

        self.db.save_snapshot(

            state_type=
                "ROOT_CAUSE",

            payload=result,
        )

        return result

    # =================================================
    # Intervention Impact
    # =================================================

    def evaluate_intervention(

        self,

        intervention_name,
        before_state,
        after_state,
    ):

        before_survival = (
            1.0 -
            before_state.get(
                "collapse_probability",
                0.0
            )
        )

        after_survival = (
            1.0 -
            after_state.get(
                "collapse_probability",
                0.0
            )
        )

        delta = round(

            after_survival
            -
            before_survival,

            4
        )

        intervention = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "intervention":
                intervention_name,

            "before_survival":
                before_survival,

            "after_survival":
                after_survival,

            "impact":
                delta,

            "successful":
                delta > 0,
        }

        self.interventions.append(
            intervention
        )

        # =================================================
        # alerts
        # =================================================

        if delta < -0.15:

            self.alerts.emit(

                level="WARNING",

                title=(
                    "NEGATIVE INTERVENTION"
                ),

                message=(
                    intervention_name
                    + " reduced survival"
                ),
            )

        self.audit.log(

            category=
                "CAUSAL_ENGINE",

            action=
                "INTERVENTION",

            severity="WARNING",

            metadata=intervention,
        )

        return intervention

    # =================================================
    # Failure Cascade
    # =================================================

    def cascade_analysis(

        self,

        origin_event,
        depth=3,
    ):

        visited = set()

        cascade = []

        self._cascade_walk(

            current=
                origin_event,

            depth=
                depth,

            visited=
                visited,

            cascade=
                cascade,
        )

        return {

            "origin":
                origin_event,

            "depth":
                depth,

            "cascade":
                cascade,
        }

    # =================================================
    # Recursive Cascade Walk
    # =================================================

    def _cascade_walk(

        self,

        current,
        depth,
        visited,
        cascade,
    ):

        if depth <= 0:
            return

        if current in visited:
            return

        visited.add(current)

        effects = self.graph.get(
            current,
            []
        )

        for effect in effects:

            cascade.append({

                "cause":
                    current,

                "effect":
                    effect[
                        "effect"
                    ],

                "confidence":
                    effect[
                        "confidence"
                    ],
            })

            self._cascade_walk(

                current=
                    effect[
                        "effect"
                    ],

                depth=
                    depth - 1,

                visited=
                    visited,

                cascade=
                    cascade,
            )

    # =================================================
    # Attribution Score
    # =================================================

    def attribution_score(
        self,
    ):

        if not self.interventions:
            return 0.0

        impacts = [

            i["impact"]

            for i in (
                self.interventions
            )
        ]

        return round(

            statistics.mean(
                impacts
            ),

            4
        )

    # =================================================
    # Most Dangerous Causes
    # =================================================

    def dangerous_causes(
        self,
        top_n=5,
    ):

        danger_map = defaultdict(
            float
        )

        for link in (
            self.causal_links
        ):

            cause = link[
                "cause"
            ][
                "event_type"
            ]

            confidence = link[
                "confidence"
            ]

            danger_map[
                cause
            ] += confidence

        ranked = sorted(

            danger_map.items(),

            key=lambda x: x[1],

            reverse=True,
        )

        return ranked[:top_n]

    # =================================================
    # Most Beneficial Causes
    # =================================================

    def beneficial_interventions(
        self,
        top_n=5,
    ):

        successful = [

            i for i in (
                self.interventions
            )

            if i["successful"]
        ]

        successful.sort(

            key=lambda x:
                x["impact"],

            reverse=True,
        )

        return successful[:top_n]

    # =================================================
    # Summary
    # =================================================

    def summary(
        self,
    ):

        return {

            "events":
                len(
                    self.events
                ),

            "causal_links":
                len(
                    self.causal_links
                ),

            "interventions":
                len(
                    self.interventions
                ),

            "root_analyses":
                len(
                    self.root_causes
                ),

            "attribution_score":
                self
                .attribution_score(),
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

            "dangerous_causes":
                self
                .dangerous_causes(),

            "beneficial":
                self
                .beneficial_interventions(),

            "last_analysis":
                self.last_analysis,
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    engine = (
        CausalEngine()
    )

    market_crash = (
        engine.register_event(

            event_type=
                "MARKET_CRASH",

            severity=0.9,
        )
    )

    liquidity_failure = (
        engine.register_event(

            event_type=
                "LIQUIDITY_FAILURE",

            severity=0.8,
        )
    )

    system_panic = (
        engine.register_event(

            event_type=
                "SYSTEM_PANIC",

            severity=0.7,
        )
    )

    engine.link_events(

        market_crash,

        liquidity_failure,

        confidence=0.91,
    )

    engine.link_events(

        liquidity_failure,

        system_panic,

        confidence=0.88,
    )

    print(

        engine.root_cause_analysis(
            "SYSTEM_PANIC"
        )
    )

    before = {

        "collapse_probability":
            0.45
    }

    after = {

        "collapse_probability":
            0.22
    }

    print(

        engine.evaluate_intervention(

            "REDUCE_EXPOSURE",

            before_state=
                before,

            after_state=
                after,
        )
    )

    print(

        engine.cascade_analysis(
            "MARKET_CRASH",
            depth=5,
        )
    )

    print(
        engine.summary()
    )

    print(
        engine.diagnostics()
    )