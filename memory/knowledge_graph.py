# memory/knowledge_graph.py

import os
import json
import hashlib

from datetime import datetime
from collections import defaultdict


class KnowledgeGraph:
    """
    Long-Term Survival Memory

    目的:
    - structured memory
    - causal relationships
    - regime intelligence
    - survival knowledge persistence

    最重要:
    「経験を知識へ変換する」
    """

    def __init__(

        self,

        graph_path=(
            "memory/knowledge_graph.json"
        ),
    ):

        self.graph_path = (
            graph_path
        )

        os.makedirs(
            "memory",
            exist_ok=True,
        )

        # =================================================
        # graph structure
        # =================================================

        self.nodes = {}

        self.edges = []

        self.statistics = defaultdict(
            int
        )

        # =================================================
        # load previous memory
        # =================================================

        self.load()

    # =================================================
    # Node ID
    # =================================================

    def node_id(
        self,
        node_type,
        value,
    ):

        raw = (
            f"{node_type}:{value}"
        )

        return hashlib.md5(

            raw.encode("utf-8")
        ).hexdigest()

    # =================================================
    # Add Node
    # =================================================

    def add_node(

        self,

        node_type,
        value,
        metadata=None,
    ):

        nid = self.node_id(
            node_type,
            value,
        )

        if nid not in self.nodes:

            self.nodes[nid] = {

                "id":
                    nid,

                "type":
                    node_type,

                "value":
                    value,

                "metadata":
                    metadata or {},

                "created_at":
                    datetime.utcnow()
                    .isoformat(),

                "updated_at":
                    datetime.utcnow()
                    .isoformat(),

                "mentions":
                    1,
            }

        else:

            self.nodes[nid][
                "mentions"
            ] += 1

            self.nodes[nid][
                "updated_at"
            ] = (
                datetime.utcnow()
                .isoformat()
            )

        return nid

    # =================================================
    # Add Edge
    # =================================================

    def add_edge(

        self,

        source_id,
        target_id,
        relation,
        weight=1.0,
        metadata=None,
    ):

        edge = {

            "source":
                source_id,

            "target":
                target_id,

            "relation":
                relation,

            "weight":
                float(weight),

            "metadata":
                metadata or {},

            "timestamp":
                datetime.utcnow()
                .isoformat(),
        }

        self.edges.append(
            edge
        )

        self.statistics[
            relation
        ] += 1

        return edge

    # =================================================
    # Learn Relationship
    # =================================================

    def learn(

        self,

        regime,
        model,
        mutation,
        outcome,
        fitness,
    ):

        # =================================================
        # nodes
        # =================================================

        regime_id = self.add_node(

            "REGIME",
            regime,
        )

        model_id = self.add_node(

            "MODEL",
            model,
        )

        mutation_id = self.add_node(

            "MUTATION",
            mutation,
        )

        outcome_id = self.add_node(

            "OUTCOME",
            outcome,
        )

        # =================================================
        # relations
        # =================================================

        self.add_edge(

            regime_id,

            mutation_id,

            relation="FAVORS",

            weight=fitness,
        )

        self.add_edge(

            mutation_id,

            model_id,

            relation="MODIFIES",

            weight=fitness,
        )

        self.add_edge(

            model_id,

            outcome_id,

            relation="PRODUCES",

            weight=fitness,
        )

        self.add_edge(

            regime_id,

            outcome_id,

            relation="CAUSES",

            weight=fitness,
        )

        return {

            "regime":
                regime_id,

            "model":
                model_id,

            "mutation":
                mutation_id,

            "outcome":
                outcome_id,
        }

    # =================================================
    # Query Related
    # =================================================

    def related(

        self,

        value,
        relation=None,
    ):

        results = []

        matching_ids = []

        for nid, node in (
            self.nodes.items()
        ):

            if node["value"] == value:

                matching_ids.append(
                    nid
                )

        for edge in self.edges:

            if relation:

                if (
                    edge["relation"]
                    != relation
                ):

                    continue

            if (
                edge["source"]
                in matching_ids
            ):

                target = self.nodes.get(
                    edge["target"]
                )

                if target:

                    results.append({

                        "relation":
                            edge[
                                "relation"
                            ],

                        "target":
                            target[
                                "value"
                            ],

                        "weight":
                            edge[
                                "weight"
                            ],
                    })

        results = sorted(

            results,

            key=lambda x:
                x["weight"],

            reverse=True,
        )

        return results

    # =================================================
    # Best Strategies
    # =================================================

    def best_mutations(
        self,
        regime,
    ):

        relations = self.related(

            regime,

            relation="FAVORS",
        )

        return relations[:10]

    # =================================================
    # Failure Patterns
    # =================================================

    def failure_patterns(
        self,
    ):

        failures = []

        for edge in self.edges:

            if (
                edge["relation"]
                == "CAUSES"
            ):

                target = self.nodes.get(
                    edge["target"]
                )

                if not target:
                    continue

                value = target[
                    "value"
                ]

                if value in {

                    "COLLAPSE",

                    "FAILURE",

                    "DRIFT",
                }:

                    source = self.nodes.get(
                        edge["source"]
                    )

                    failures.append({

                        "source":
                            source[
                                "value"
                            ],

                        "outcome":
                            value,

                        "weight":
                            edge[
                                "weight"
                            ],
                    })

        failures = sorted(

            failures,

            key=lambda x:
                x["weight"],

            reverse=True,
        )

        return failures

    # =================================================
    # Survival Intelligence
    # =================================================

    def survival_intelligence(
        self,
    ):

        intelligence = {}

        # =================================================
        # strongest regime
        # =================================================

        regime_scores = defaultdict(
            float
        )

        for edge in self.edges:

            if (
                edge["relation"]
                == "FAVORS"
            ):

                source = self.nodes.get(
                    edge["source"]
                )

                if source:

                    regime_scores[
                        source["value"]
                    ] += edge[
                        "weight"
                    ]

        intelligence[
            "regime_scores"
        ] = dict(
            regime_scores
        )

        # =================================================
        # mutation success
        # =================================================

        mutation_scores = defaultdict(
            float
        )

        for edge in self.edges:

            if (
                edge["relation"]
                == "MODIFIES"
            ):

                source = self.nodes.get(
                    edge["source"]
                )

                if source:

                    mutation_scores[
                        source["value"]
                    ] += edge[
                        "weight"
                    ]

        intelligence[
            "mutation_scores"
        ] = dict(
            mutation_scores
        )

        return intelligence

    # =================================================
    # Save
    # =================================================

    def save(
        self,
    ):

        payload = {

            "saved_at":
                datetime.utcnow()
                .isoformat(),

            "nodes":
                self.nodes,

            "edges":
                self.edges,

            "statistics":
                dict(
                    self.statistics
                ),
        }

        with open(

            self.graph_path,

            "w",

            encoding="utf-8",
        ) as f:

            json.dump(

                payload,

                f,

                indent=2,

                ensure_ascii=False,
            )

        print(
            "[KNOWLEDGE SAVED]"
        )

    # =================================================
    # Load
    # =================================================

    def load(
        self,
    ):

        if not os.path.exists(
            self.graph_path
        ):

            return

        try:

            with open(

                self.graph_path,

                "r",

                encoding="utf-8",
            ) as f:

                payload = json.load(
                    f
                )

            self.nodes = payload.get(
                "nodes",
                {},
            )

            self.edges = payload.get(
                "edges",
                [],
            )

            self.statistics.update(

                payload.get(
                    "statistics",
                    {},
                )
            )

            print(
                "[KNOWLEDGE LOADED]"
            )

        except Exception as e:

            print(
                "[KNOWLEDGE LOAD ERROR]",
                e,
            )

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "nodes":
                len(
                    self.nodes
                ),

            "edges":
                len(
                    self.edges
                ),

            "relations":
                dict(
                    self.statistics
                ),

            "graph_path":
                self.graph_path,
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    graph = (
        KnowledgeGraph()
    )

    graph.learn(

        regime="DRIFT",

        model="rf_large",

        mutation="feature_mul",

        outcome="RECOVERY",

        fitness=0.82,
    )

    graph.learn(

        regime="COLLAPSE",

        model="logistic",

        mutation="feature_sub",

        outcome="FAILURE",

        fitness=0.15,
    )

    graph.save()

    print(
        graph.best_mutations(
            "DRIFT"
        )
    )

    print(
        graph.failure_patterns()
    )

    print(
        graph.survival_intelligence()
    )

    print(
        graph.diagnostics()
    )