# core/meta_cognition.py

import statistics
import math
import os

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

from core.knowledge_graph import (
    KnowledgeGraph
)

from core.alignment_constitution import (
    AlignmentConstitution
)


class CognitiveState:
    """
    Civilization Cognitive Snapshot
    """

    def __init__(
        self,
    ):

        self.timestamp = (
            datetime.utcnow()
            .isoformat()
        )

        self.confidence = 1.0

        self.uncertainty = 0.0

        self.cognitive_load = 0.0

        self.stability = 1.0

        self.self_awareness = 0.0

        self.contradictions = 0

        self.reflection_score = 0.0

    def serialize(
        self,
    ):

        return {

            "timestamp":
                self.timestamp,

            "confidence":
                self.confidence,

            "uncertainty":
                self.uncertainty,

            "cognitive_load":
                self.cognitive_load,

            "stability":
                self.stability,

            "self_awareness":
                self.self_awareness,

            "contradictions":
                self.contradictions,

            "reflection_score":
                self.reflection_score,
        }


# =====================================================
# Meta Cognition
# =====================================================

class MetaCognition:
    """
    Civilization Self-Awareness Layer

    目的:
    - self observation
    - confidence estimation
    - contradiction awareness
    - strategic reflection
    - cognitive stabilization

    最重要:
    「文明が自分自身を理解する」
    """

    def __init__(
        self,
    ):

        # If environment requests disabling meta cognition (production hardening),
        # initialize a minimal, lightweight instance and avoid heavy I/O.
        if os.environ.get("DISABLE_META", "0").lower() in ("1", "true", "yes"):
            self.db = None
            self.audit = None
            self.alerts = None
            self.graph = None
            self.constitution = None
            self.state = CognitiveState()
            self.history = []
            self.reflections = []
            self.identity_vector = {}
            self.max_uncertainty = 0.7
            self.max_load = 0.85
            self.min_stability = 0.3
            self.min_confidence = 0.2
            return

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
        # external systems
        # =================================================

        self.graph = (
            KnowledgeGraph()
        )

        self.constitution = (
            AlignmentConstitution()
        )

        # =================================================
        # cognitive state
        # =================================================

        self.state = (
            CognitiveState()
        )

        self.history = []

        self.reflections = []

        self.identity_vector = {}

        # =================================================
        # thresholds
        # =================================================

        self.max_uncertainty = 0.7

        self.max_load = 0.85

        self.min_stability = 0.3

        self.min_confidence = 0.2

    # =================================================
    # Evaluate Confidence
    # =====================================================

    def evaluate_confidence(

        self,

        signals,
    ):

        if not signals:

            self.state.confidence = (
                0.0
            )

            return 0.0

        values = [

            max(
                0.0,
                min(1.0, s)
            )

            for s in signals
        ]

        confidence = (
            statistics.mean(
                values
            )
        )

        self.state.confidence = round(
            confidence,
            4
        )

        self.state.uncertainty = round(

            1.0 - confidence,

            4
        )

        return self.state.confidence

    # =================================================
    # Evaluate Cognitive Load
    # =====================================================

    def evaluate_load(

        self,

        active_processes,
        event_rate,
    ):

        load = min(

            1.0,

            (
                active_processes * 0.05
            )
            +
            (
                event_rate * 0.1
            )
        )

        self.state.cognitive_load = (
            round(load, 4)
        )

        return self.state.cognitive_load

    # =================================================
    # Evaluate Stability
    # =====================================================

    def evaluate_stability(
        self,
    ):

        components = [

            self.state.confidence,

            1.0
            -
            self.state.uncertainty,

            1.0
            -
            self.state.cognitive_load,
        ]

        stability = (
            statistics.mean(
                components
            )
        )

        stability = max(
            0.0,
            min(1.0, stability)
        )

        self.state.stability = round(
            stability,
            4
        )

        return self.state.stability

    # =================================================
    # Evaluate Self Awareness
    # =====================================================

    def evaluate_self_awareness(
        self,
    ):

        contradiction_penalty = min(

            1.0,

            self.state.contradictions
            / 10.0
        )

        awareness = max(

            0.0,

            (
                self.state.stability
                *
                0.5
            )
            +
            (
                self.state.confidence
                *
                0.5
            )
            -
            contradiction_penalty
        )

        self.state.self_awareness = (
            round(
                awareness,
                4
            )
        )

        return self.state.self_awareness

    # =================================================
    # Reflection
    # =====================================================

    def reflect(

        self,

        decisions,
    ):

        if not decisions:

            score = 0.0

        else:

            successful = [

                d.get(
                    "success",
                    False
                )

                for d in decisions
            ]

            success_ratio = (

                sum(successful)
                /
                len(successful)
            )

            score = round(
                success_ratio,
                4
            )

        reflection = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "reflection_score":
                score,

            "decision_count":
                len(decisions),
        }

        self.reflections.append(
            reflection
        )

        self.reflections = (
            self.reflections[
                -1000:
            ]
        )

        self.state.reflection_score = (
            score
        )

        return reflection

    # =================================================
    # Detect Contradictions
    # =====================================================

    def detect_contradictions(
        self,
    ):

        contradictions = (
            self.graph
            .detect_contradictions()
        )

        count = len(
            contradictions
        )

        self.state.contradictions = (
            count
        )

        if count > 0:

            self.alerts.emit(

                level="WARNING",

                title=
                    "COGNITIVE_CONTRADICTION",

                message=(
                    "internal contradictions detected"
                ),
            )

        return contradictions

    # =================================================
    # Constitution Consistency
    # =====================================================

    def constitution_consistency(
        self,
    ):

        integrity = (
            self.constitution
            .integrity_check()
        )
        return integrity.get(
            "intact",
            False
        )

    # =================================================
    # Identity Update
    # =====================================================

    def update_identity(

        self,

        traits,
    ):

        for key, value in (
            traits.items()
        ):

            existing = (
                self.identity_vector
                .get(key, 0.5)
            )

            updated = (

                existing * 0.8
                +
                value * 0.2
            )

            self.identity_vector[
                key
            ] = round(
                updated,
                4
            )

        return self.identity_vector

    # =================================================
    # Cognitive Cycle
    # =====================================================

    def cognitive_cycle(

        self,

        signals,
        active_processes,
        event_rate,
        decisions,
    ):

        self.evaluate_confidence(
            signals
        )

        self.evaluate_load(

            active_processes=
                active_processes,

            event_rate=
                event_rate,
        )

        self.evaluate_stability()

        self.detect_contradictions()

        self.evaluate_self_awareness()

        reflection = self.reflect(
            decisions
        )

        consistent = (
            self.constitution_consistency()
        )

        snapshot = self.snapshot()

        snapshot[
            "constitution_integrity"
        ] = consistent

        snapshot[
            "reflection"
        ] = reflection

        self.history.append(
            snapshot
        )

        self.history = (
            self.history[-1000:]
        )

        self.persist(snapshot)

        self.evaluate_risk()

        return snapshot

    # =================================================
    # Evaluate Cognitive Risk
    # =====================================================

    def evaluate_risk(
        self,
    ):

        if (
            self.state.uncertainty
            > self.max_uncertainty
        ):

            self.alerts.emit(

                level="WARNING",

                title=
                    "HIGH_UNCERTAINTY",

                message=(
                    "cognitive uncertainty elevated"
                ),
            )

        if (
            self.state.cognitive_load
            > self.max_load
        ):

            self.alerts.emit(

                level="WARNING",

                title=
                    "COGNITIVE_OVERLOAD",

                message=(
                    "cognitive load critical"
                ),
            )

        if (
            self.state.stability
            < self.min_stability
        ):

            self.alerts.emit(

                level="CRITICAL",

                title=
                    "COGNITIVE_INSTABILITY",

                message=(
                    "civilization instability detected"
                ),
            )

        if (
            self.state.confidence
            < self.min_confidence
        ):

            self.alerts.emit(

                level="WARNING",

                title=
                    "LOW_CONFIDENCE",

                message=(
                    "decision confidence degraded"
                ),
            )

    # =================================================
    # Snapshot
    # =====================================================

    def snapshot(
        self,
    ):

        return {

            "state":
                self.state.serialize(),

            "identity":
                self.identity_vector,

            "history_size":
                len(
                    self.history
                ),

            "reflections":
                len(
                    self.reflections
                ),
        }

    # =================================================
    # Persist
    # =====================================================

    def persist(

        self,

        payload,
    ):

        self.db.save_snapshot(

            state_type=
                "META_COGNITION",

            payload=payload,
        )

        self.audit.log(

            category=
                "META_COGNITION",

            action=
                "COGNITIVE_CYCLE",

            severity="INFO",

            metadata=payload,
        )

    # =================================================
    # Diagnostics
    # =====================================================

    def diagnostics(
        self,
    ):

        return {

            "snapshot":
                self.snapshot(),

            "latest_reflection":
                (
                    self.reflections[-1]
                    if self.reflections
                    else None
                ),
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    cognition = (
        MetaCognition()
    )

    cognition.graph.add_relationship(

        source_name=
            "Market Crash",

        target_name=
            "Liquidity Stress",

        relation_type=
            "CAUSES",

        weight=0.9,
    )

    cognition.graph.add_relationship(

        source_name=
            "Market Crash",

        target_name=
            "Liquidity Stress",

        relation_type=
            "PREVENTS",

        weight=0.2,
    )

    snapshot = (

        cognition.cognitive_cycle(

            signals=[
                0.8,
                0.7,
                0.9,
            ],

            active_processes=8,

            event_rate=3,

            decisions=[

                {"success": True},
                {"success": True},
                {"success": False},
            ],
        )
    )

    print(snapshot)

    print(
        cognition.diagnostics()
    )
