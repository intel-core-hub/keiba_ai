# core/knowledge_graph.py

import uuid
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


# =====================================================
# Entity
# =====================================================

class Entity:
    """
    Knowledge Graph Entity
    """

    def __init__(

        self,

        name,
        entity_type,
        attributes=None,
    ):

        self.id = str(
            uuid.uuid4()
        )

        self.created_at = (
            datetime.utcnow()
            .isoformat()
        )

        self.name = name

        self.entity_type = (
            entity_type
        )

        self.attributes = (
            attributes or {}
        )

    def serialize(
        self,
    ):

        return {

            "id":
                self.id,

            "created_at":
                self.created_at,

            "name":
                self.name,

            "entity_type":
                self.entity_type,

            "attributes":
                self.attributes,
        }


# =====================================================
# Relationship
# =====================================================

class Relationship:
    """
    Entity Relationship
    """

    def __init__(

        self,

        source_id,
        target_id,
        relation_type,
        weight=0.5,
        metadata=None,
    ):

        self.id = str(
            uuid.uuid4()
        )

        self.created_at = (
            datetime.utcnow()
            .isoformat()
        )

        self.source_id = (
            source_id
        )

        self.target_id = (
            target_id
        )

        self.relation_type = (
            relation_type
        )

        self.weight = weight

        self.metadata = (
            metadata or {}
        )

    def serialize(
        self,
    ):

        return {

            "id":
                self.id,

            "created_at":
                self.created_at,

            "source_id":
                self.source_id,

            "target_id":
                self.target_id,

            "relation_type":
                self.relation_type,

            "weight":
                self.weight,

            "metadata":
                self.metadata,
        }


# =====================================================
# Knowledge Graph
# =====================================================

class KnowledgeGraph:
    """
    Civilization Knowledge Structure

    目的:
    - structured world knowledge
    - entity relationships
    - semantic reasoning
    - strategic intelligence

    最重要:
    「世界知識を構造として理解する」
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
        # graph storage
        # =================================================

        self.entities = {}

        self.relationships = {}

        # =================================================
        # indexes
        # =================================================

        self.entity_by_name = {}

        self.adjacency = defaultdict(
            list
        )

        self.reverse_adjacency = (
            defaultdict(list)
        )

        # =================================================
        # metrics
        # =================================================

        self.total_inferences = 0

        self.contradictions = []

        self.last_update = None

    # =================================================
    # Add Entity
    # =====================================================

    def add_entity(

        self,

        name,
        entity_type,
        attributes=None,
    ):

        if name in (
            self.entity_by_name
        ):

            return self.entities[

                self.entity_by_name[
                    name
                ]
            ]

        entity = Entity(

            name=name,

            entity_type=
                entity_type,

            attributes=
                attributes,
        )

        self.entities[
            entity.id
        ] = entity

        self.entity_by_name[
            name
        ] = entity.id

        self.last_update = (
            datetime.utcnow()
            .isoformat()
        )

        self.audit.log(

            category=
                "KNOWLEDGE_GRAPH",

            action=
                "ADD_ENTITY",

            severity="INFO",

            metadata=
                entity.serialize(),
        )

        return entity

    # =================================================
    # Add Relationship
    # =====================================================

    def add_relationship(

        self,

        source_name,
        target_name,
        relation_type,
        weight=0.5,
        metadata=None,
    ):

        source = (
            self.get_or_create(
                source_name
            )
        )

        target = (
            self.get_or_create(
                target_name
            )
        )

        relationship = Relationship(

            source_id=
                source.id,

            target_id=
                target.id,

            relation_type=
                relation_type,

            weight=weight,

            metadata=metadata,
        )

        self.relationships[
            relationship.id
        ] = relationship

        self.adjacency[
            source.id
        ].append(
            relationship.id
        )

        self.reverse_adjacency[
            target.id
        ].append(
            relationship.id
        )

        self.last_update = (
            datetime.utcnow()
            .isoformat()
        )

        self.audit.log(

            category=
                "KNOWLEDGE_GRAPH",

            action=
                "ADD_RELATIONSHIP",

            severity="INFO",

            metadata=
                relationship.serialize(),
        )

        return relationship

    # =================================================
    # Get or Create Entity
    # =====================================================

    def get_or_create(

        self,

        name,
    ):

        if name in (
            self.entity_by_name
        ):

            entity_id = (
                self.entity_by_name[
                    name
                ]
            )

            return self.entities[
                entity_id
            ]

        return self.add_entity(

            name=name,

            entity_type=
                "UNKNOWN",
        )

    # =================================================
    # Find Entity
    # =====================================================

    def find_entity(

        self,

        name,
    ):

        entity_id = (
            self.entity_by_name.get(
                name
            )
        )

        if not entity_id:
            return None

        return self.entities[
            entity_id
        ]

    # =================================================
    # Get Relationships
    # =====================================================

    def relationships_of(

        self,

        entity_name,
    ):

        entity = self.find_entity(
            entity_name
        )

        if not entity:
            return []

        rel_ids = self.adjacency[
            entity.id
        ]

        return [

            self.relationships[r]

            for r in rel_ids
        ]

    # =================================================
    # Infer Connections
    # =====================================================

    def infer_connections(

        self,

        entity_name,
        depth=2,
    ):

        entity = self.find_entity(
            entity_name
        )

        if not entity:
            return []

        visited = set()

        results = []

        self._walk(

            current_id=
                entity.id,

            depth=depth,

            visited=visited,

            results=results,
        )

        self.total_inferences += 1

        return results

    # =================================================
    # Recursive Walk
    # =====================================================

    def _walk(

        self,

        current_id,
        depth,
        visited,
        results,
    ):

        if depth <= 0:
            return

        if current_id in visited:
            return

        visited.add(current_id)

        rel_ids = self.adjacency[
            current_id
        ]

        for rel_id in rel_ids:

            rel = self.relationships[
                rel_id
            ]

            target = self.entities[
                rel.target_id
            ]

            results.append({

                "source":
                    self.entities[
                        rel.source_id
                    ].name,

                "target":
                    target.name,

                "relation":
                    rel.relation_type,

                "weight":
                    rel.weight,
            })

            self._walk(

                current_id=
                    target.id,

                depth=
                    depth - 1,

                visited=
                    visited,

                results=
                    results,
            )

    # =================================================
    # Contradiction Detection
    # =====================================================

    def detect_contradictions(
        self,
    ):

        contradictions = []

        grouped = defaultdict(
            list
        )

        for rel in (
            self.relationships.values()
        ):

            key = (

                rel.source_id,

                rel.target_id
            )

            grouped[key].append(
                rel
            )

        for key, rels in (
            grouped.items()
        ):

            relation_types = set(

                r.relation_type

                for r in rels
            )

            # simplistic contradiction rule
            if (
                "CAUSES" in relation_types
                and
                "PREVENTS"
                in relation_types
            ):

                contradictions.append({

                    "pair":
                        key,

                    "relations":
                        list(
                            relation_types
                        ),
                })

        self.contradictions = (
            contradictions
        )

        return contradictions

    # =================================================
    # Strategic Importance
    # =====================================================

    def strategic_importance(

        self,

        entity_name,
    ):

        entity = self.find_entity(
            entity_name
        )

        if not entity:
            return 0.0

        outgoing = len(

            self.adjacency[
                entity.id
            ]
        )

        incoming = len(

            self.reverse_adjacency[
                entity.id
            ]
        )

        importance = (
            outgoing + incoming
        )

        normalized = min(

            1.0,

            importance / 10.0
        )

        return round(
            normalized,
            4
        )

    # =================================================
    # Predict Cascades
    # =====================================================

    def predict_cascades(

        self,

        entity_name,
    ):

        inferred = (
            self.infer_connections(

                entity_name,

                depth=3,
            )
        )

        cascades = []

        for item in inferred:

            if (
                item["weight"]
                > 0.7
            ):

                cascades.append(
                    item
                )

        return cascades

    # =================================================
    # Snapshot
    # =====================================================

    def snapshot(
        self,
    ):

        return {

            "entities":
                len(
                    self.entities
                ),

            "relationships":
                len(
                    self.relationships
                ),

            "inferences":
                self.total_inferences,

            "contradictions":
                len(
                    self.contradictions
                ),

            "last_update":
                self.last_update,
        }

    # =================================================
    # Persist
    # =====================================================

    def persist(
        self,
    ):

        payload = {

            "entities": [

                e.serialize()

                for e in (
                    self.entities.values()
                )
            ],

            "relationships": [

                r.serialize()

                for r in (
                    self.relationships
                    .values()
                )
            ],

            "snapshot":
                self.snapshot(),
        }

        self.db.save_snapshot(

            state_type=
                "KNOWLEDGE_GRAPH",

            payload=payload,
        )

        return True

    # =================================================
    # Diagnostics
    # =====================================================

    def diagnostics(
        self,
    ):

        return {

            "snapshot":
                self.snapshot(),

            "top_contradictions":
                self.contradictions[
                    :10
                ],
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    graph = (
        KnowledgeGraph()
    )

    graph.add_entity(

        name=
            "Market Crash",

        entity_type=
            "EVENT",
    )

    graph.add_entity(

        name=
            "Liquidity Stress",

        entity_type=
            "RISK",
    )

    graph.add_entity(

        name=
            "Survival Threat",

        entity_type=
            "THREAT",
    )

    graph.add_relationship(

        source_name=
            "Market Crash",

        target_name=
            "Liquidity Stress",

        relation_type=
            "CAUSES",

        weight=0.91,
    )

    graph.add_relationship(

        source_name=
            "Liquidity Stress",

        target_name=
            "Survival Threat",

        relation_type=
            "CAUSES",

        weight=0.88,
    )

    print(
        graph.snapshot()
    )

    print(

        graph.infer_connections(
            "Market Crash"
        )
    )

    print(

        graph.predict_cascades(
            "Market Crash"
        )
    )

    print(

        graph.strategic_importance(
            "Liquidity Stress"
        )
    )

    print(
        graph.detect_contradictions()
    )

    print(
        graph.diagnostics()
    )