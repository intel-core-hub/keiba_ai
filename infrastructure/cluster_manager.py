# infrastructure/cluster_manager.py

import os
import json
import time
import uuid
import threading

from datetime import datetime, timedelta

from infrastructure.database import (
    SurvivalDatabase
)

from core.audit_logger import (
    AuditLogger
)

from core.alert_manager import (
    AlertManager
)


class ClusterManager:
    """
    Distributed Survival Coordination

    目的:
    - node federation
    - cluster coordination
    - failover survival
    - distributed orchestration

    最重要:
    「個体群として生き残る」
    """

    def __init__(

        self,

        cluster_name=(
            "survival_cluster"
        ),

        heartbeat_timeout=15,
    ):

        # =================================================
        # identity
        # =================================================

        self.cluster_id = str(
            uuid.uuid4()
        )

        self.cluster_name = (
            cluster_name
        )

        # =================================================
        # node state
        # =================================================

        self.nodes = {}

        self.dead_nodes = {}

        self.leader_node = None

        # =================================================
        # routing
        # =================================================

        self.task_routes = {}

        self.routing_history = []

        # =================================================
        # timing
        # =================================================

        self.heartbeat_timeout = (
            heartbeat_timeout
        )

        self.last_health_check = None

        # =================================================
        # runtime
        # =================================================

        self.running = False

        self.lock = threading.Lock()

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
        # persistence
        # =================================================

        self.cluster_path = (
            "infrastructure/"
            "cluster_state.json"
        )

        os.makedirs(
            "infrastructure",
            exist_ok=True,
        )

    # =================================================
    # Start Cluster
    # =================================================

    def start(
        self,
    ):

        if self.running:
            return

        self.running = True

        health_thread = (
            threading.Thread(

                target=self.health_loop,

                daemon=True,
            )
        )

        health_thread.start()

        self.audit.log(

            category="CLUSTER",

            action="START",

            severity="INFO",

            metadata={
                "cluster_id":
                    self.cluster_id
            },
        )

        print(
            "[CLUSTER STARTED]"
        )

    # =================================================
    # Stop Cluster
    # =================================================

    def stop(
        self,
    ):

        self.running = False

        self.persist_state()

        self.audit.log(

            category="CLUSTER",

            action="STOP",

            severity="WARNING",
        )

        print(
            "[CLUSTER STOPPED]"
        )

    # =================================================
    # Register Node
    # =================================================

    def register_node(

        self,

        node_info,
    ):

        node_id = node_info[
            "node_id"
        ]

        with self.lock:

            self.nodes[node_id] = {

                **node_info,

                "registered_at":
                    datetime.utcnow()
                    .isoformat(),

                "last_seen":
                    datetime.utcnow()
                    .isoformat(),

                "status":
                    "ACTIVE",
            }

        # =================================================
        # leader election
        # =================================================

        if not self.leader_node:

            self.leader_node = (
                node_id
            )

        self.audit.log(

            category="CLUSTER",

            action="REGISTER_NODE",

            severity="INFO",

            metadata=node_info,
        )

        return {

            "registered":
                True,

            "leader":
                self.leader_node,
        }

    # =================================================
    # Heartbeat
    # =================================================

    def heartbeat(

        self,

        node_id,
    ):

        with self.lock:

            if node_id not in (
                self.nodes
            ):

                return {
                    "error":
                        "unknown node"
                }

            self.nodes[node_id][
                "last_seen"
            ] = (
                datetime.utcnow()
                .isoformat()
            )

            self.nodes[node_id][
                "status"
            ] = "ACTIVE"

        return {

            "heartbeat":
                "OK",

            "leader":
                self.leader_node,
        }

    # =================================================
    # Health Monitoring
    # =================================================

    def health_loop(
        self,
    ):

        while self.running:

            try:

                self.detect_dead_nodes()

                self.elect_leader()

                self.persist_state()

                self.last_health_check = (
                    datetime.utcnow()
                    .isoformat()
                )

                time.sleep(5)

            except Exception as e:

                print(
                    "[CLUSTER ERROR]",
                    e,
                )

    # =================================================
    # Detect Dead Nodes
    # =================================================

    def detect_dead_nodes(
        self,
    ):

        now = datetime.utcnow()

        dead = []

        with self.lock:

            for node_id, node in (
                self.nodes.items()
            ):

                last_seen = (
                    datetime.fromisoformat(
                        node[
                            "last_seen"
                        ]
                    )
                )

                delta = (
                    now - last_seen
                ).total_seconds()

                if (
                    delta >
                    self.heartbeat_timeout
                ):

                    node["status"] = (
                        "DEAD"
                    )

                    self.dead_nodes[
                        node_id
                    ] = node

                    dead.append(
                        node_id
                    )

            for node_id in dead:

                self.nodes.pop(
                    node_id,
                    None
                )

        # =================================================
        # alert
        # =================================================

        for node_id in dead:

            self.alerts.emit(

                level="CRITICAL",

                title="NODE FAILURE",

                message=(
                    f"{node_id} "
                    f"became unreachable"
                ),
            )

            self.audit.log(

                category="CLUSTER",

                action="NODE_DEAD",

                severity="ERROR",

                metadata={
                    "node_id":
                        node_id
                },
            )

    # =================================================
    # Leader Election
    # =================================================

    def elect_leader(
        self,
    ):

        with self.lock:

            if not self.nodes:

                self.leader_node = (
                    None
                )

                return None

            # =============================================
            # stable deterministic election
            # =============================================

            leader = sorted(
                self.nodes.keys()
            )[0]

            if leader != (
                self.leader_node
            ):

                old = self.leader_node

                self.leader_node = (
                    leader
                )

                self.audit.log(

                    category="CLUSTER",

                    action=(
                        "LEADER_CHANGE"
                    ),

                    severity="WARNING",

                    metadata={

                        "old":
                            old,

                        "new":
                            leader,
                    },
                )

        return self.leader_node

    # =================================================
    # Route Task
    # =================================================

    def route_task(

        self,

        task_type,
    ):

        with self.lock:

            active_nodes = [

                node

                for node in (
                    self.nodes.values()
                )

                if node[
                    "status"
                ] == "ACTIVE"
            ]

            if not active_nodes:

                return None

            # =============================================
            # naive load balancing
            # =============================================

            selected = min(

                active_nodes,

                key=lambda x:
                    x.get(
                        "tasks_completed",
                        0
                    ),
            )

            route = {

                "timestamp":
                    datetime.utcnow()
                    .isoformat(),

                "task_type":
                    task_type,

                "node_id":
                    selected[
                        "node_id"
                    ],
            }

            self.routing_history.append(
                route
            )

            return route

    # =================================================
    # Failover
    # =================================================

    def failover(
        self,
        failed_node_id,
    ):

        with self.lock:

            if failed_node_id in (
                self.dead_nodes
            ):

                self.audit.log(

                    category="CLUSTER",

                    action="FAILOVER",

                    severity="CRITICAL",

                    metadata={
                        "failed_node":
                            failed_node_id
                    },
                )

                return {

                    "failover":
                        True,

                    "failed":
                        failed_node_id,

                    "leader":
                        self.leader_node,
                }

        return {

            "failover":
                False
        }

    # =================================================
    # Cluster State
    # =================================================

    def persist_state(
        self,
    ):

        payload = {

            "cluster_id":
                self.cluster_id,

            "cluster_name":
                self.cluster_name,

            "leader":
                self.leader_node,

            "nodes":
                self.nodes,

            "dead_nodes":
                self.dead_nodes,

            "routing_history":
                self.routing_history[
                    -100:
                ],

            "saved_at":
                datetime.utcnow()
                .isoformat(),
        }

        with open(

            self.cluster_path,

            "w",

            encoding="utf-8",
        ) as f:

            json.dump(

                payload,

                f,

                indent=2,

                ensure_ascii=False,
            )

    # =================================================
    # Load Cluster
    # =================================================

    def load_state(
        self,
    ):

        if not os.path.exists(
            self.cluster_path
        ):

            return None

        with open(

            self.cluster_path,

            "r",

            encoding="utf-8",
        ) as f:

            payload = json.load(
                f
            )

        self.nodes = payload.get(
            "nodes",
            {}
        )

        self.dead_nodes = (
            payload.get(
                "dead_nodes",
                {}
            )
        )

        self.routing_history = (
            payload.get(
                "routing_history",
                []
            )
        )

        self.leader_node = (
            payload.get(
                "leader"
            )
        )

        return payload

    # =================================================
    # Cluster Summary
    # =================================================

    def summary(
        self,
    ):

        return {

            "cluster_id":
                self.cluster_id,

            "cluster_name":
                self.cluster_name,

            "leader":
                self.leader_node,

            "active_nodes":
                len(
                    self.nodes
                ),

            "dead_nodes":
                len(
                    self.dead_nodes
                ),

            "routes":
                len(
                    self.routing_history
                ),

            "last_health_check":
                self.last_health_check,
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

            "nodes":
                self.nodes,

            "dead":
                self.dead_nodes,
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    cluster = (
        ClusterManager()
    )

    cluster.start()

    node_a = {

        "node_id":
            "worker_A",

        "node_type":
            "SCRAPER",

        "tasks_completed":
            4,
    }

    node_b = {

        "node_id":
            "worker_B",

        "node_type":
            "SIMULATION",

        "tasks_completed":
            2,
    }

    cluster.register_node(
        node_a
    )

    cluster.register_node(
        node_b
    )

    print(
        cluster.summary()
    )

    route = cluster.route_task(
        "SIMULATION"
    )

    print(route)

    time.sleep(2)

    cluster.heartbeat(
        "worker_A"
    )

    print(
        cluster.diagnostics()
    )

    cluster.stop()