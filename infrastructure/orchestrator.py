# infrastructure/orchestrator.py

import time
import threading

from datetime import datetime

from infrastructure.cluster_manager import (
    ClusterManager
)

from infrastructure.database import (
    SurvivalDatabase
)

from infrastructure.worker_node import (
    WorkerNode
)

from core.alert_manager import (
    AlertManager
)

from core.audit_logger import (
    AuditLogger
)

from core.executive_controller import (
    ExecutiveController
)


class Orchestrator:
    """
    Predictive Survival Governance

    目的:
    - autonomous coordination
    - predictive infrastructure control
    - proactive survival management
    - adaptive resource governance

    最重要:
    「問題発生前に動く」
    """

    def __init__(

        self,

        cluster_name=(
            "survival_cluster"
        ),
    ):

        # =================================================
        # infrastructure
        # =================================================

        self.cluster = (
            ClusterManager(
                cluster_name=
                cluster_name
            )
        )

        self.db = (
            SurvivalDatabase()
        )

        self.alerts = (
            AlertManager()
        )

        self.audit = (
            AuditLogger()
        )

        self.executive = (
            ExecutiveController()
        )

        # =================================================
        # runtime
        # =================================================

        self.running = False

        self.started_at = None

        # =================================================
        # worker pools
        # =================================================

        self.workers = {}

        # =================================================
        # orchestration
        # =================================================

        self.scaling_enabled = True

        self.failover_enabled = True

        self.predictive_enabled = True

        # =================================================
        # thresholds
        # =================================================

        self.max_failures = 5

        self.max_worker_load = 20

        self.min_workers = 1

        self.max_workers = 20

        # =================================================
        # orchestration memory
        # =================================================

        self.scaling_history = []

        self.routing_history = []

        self.failover_history = []

    # =================================================
    # Start Orchestrator
    # =================================================

    def start(
        self,
    ):

        if self.running:
            return

        self.running = True

        self.started_at = (
            datetime.utcnow()
            .isoformat()
        )

        self.cluster.start()

        # =================================================
        # orchestration loops
        # =================================================

        threading.Thread(

            target=self.monitor_loop,

            daemon=True,
        ).start()

        threading.Thread(

            target=self.scaling_loop,

            daemon=True,
        ).start()

        threading.Thread(

            target=self.failover_loop,

            daemon=True,
        ).start()

        threading.Thread(

            target=self.predictive_loop,

            daemon=True,
        ).start()

        self.audit.log(

            category="ORCHESTRATOR",

            action="START",

            severity="INFO",
        )

        print(
            "[ORCHESTRATOR STARTED]"
        )

    # =================================================
    # Stop Orchestrator
    # =================================================

    def stop(
        self,
    ):

        self.running = False

        self.cluster.stop()

        for worker in (
            self.workers.values()
        ):

            worker.stop()

        self.audit.log(

            category="ORCHESTRATOR",

            action="STOP",

            severity="WARNING",
        )

        print(
            "[ORCHESTRATOR STOPPED]"
        )

    # =================================================
    # Create Worker
    # =================================================

    def create_worker(

        self,

        node_type="GENERAL",
    ):

        worker = WorkerNode(
            node_type=node_type
        )

        worker.start()

        self.workers[
            worker.node_id
        ] = worker

        self.cluster.register_node(

            worker.identity()
        )

        self.audit.log(

            category="ORCHESTRATOR",

            action="CREATE_WORKER",

            severity="INFO",

            metadata={
                "worker":
                    worker.node_id,

                "type":
                    node_type,
            },
        )

        return worker

    # =================================================
    # Remove Worker
    # =================================================

    def remove_worker(
        self,
        worker_id,
    ):

        if worker_id not in (
            self.workers
        ):

            return False

        worker = self.workers[
            worker_id
        ]

        worker.stop()

        self.workers.pop(
            worker_id,
            None
        )

        self.audit.log(

            category="ORCHESTRATOR",

            action="REMOVE_WORKER",

            severity="WARNING",

            metadata={
                "worker":
                    worker_id
            },
        )

        return True

    # =================================================
    # Monitor Loop
    # =================================================

    def monitor_loop(
        self,
    ):

        while self.running:

            try:

                self.monitor_cluster()

                time.sleep(5)

            except Exception as e:

                print(
                    "[MONITOR ERROR]",
                    e,
                )

    # =================================================
    # Monitor Cluster
    # =================================================

    def monitor_cluster(
        self,
    ):

        summary = (
            self.cluster.summary()
        )

        dead_nodes = summary[
            "dead_nodes"
        ]

        if dead_nodes > 0:

            self.alerts.emit(

                level="WARNING",

                title=(
                    "NODE FAILURES"
                ),

                message=(
                    f"{dead_nodes} "
                    f"dead nodes"
                ),
            )

        # =================================================
        # save snapshot
        # =================================================

        self.db.save_snapshot(

            state_type="CLUSTER",

            payload=summary,
        )

    # =================================================
    # Scaling Loop
    # =================================================

    def scaling_loop(
        self,
    ):

        while self.running:

            try:

                if (
                    self.scaling_enabled
                ):

                    self.evaluate_scaling()

                time.sleep(10)

            except Exception as e:

                print(
                    "[SCALING ERROR]",
                    e,
                )

    # =================================================
    # Evaluate Scaling
    # =================================================

    def evaluate_scaling(
        self,
    ):

        worker_count = len(
            self.workers
        )

        total_load = 0

        for worker in (
            self.workers.values()
        ):

            status = worker.status()

            total_load += status[
                "queue"
            ]["queued"]

        average_load = 0

        if worker_count > 0:

            average_load = (
                total_load /
                worker_count
            )

        # =================================================
        # scale up
        # =================================================

        if (

            average_load >
            self.max_worker_load

            and

            worker_count <
            self.max_workers

        ):

            worker = (
                self.create_worker(
                    "AUTO_SCALE"
                )
            )

            event = {

                "timestamp":
                    datetime.utcnow()
                    .isoformat(),

                "action":
                    "SCALE_UP",

                "worker":
                    worker.node_id,
            }

            self.scaling_history.append(
                event
            )

            self.audit.log(

                category="ORCHESTRATOR",

                action="SCALE_UP",

                severity="WARNING",

                metadata=event,
            )

        # =================================================
        # scale down
        # =================================================

        elif (

            average_load < 1

            and

            worker_count >
            self.min_workers

        ):

            removable = list(
                self.workers.keys()
            )[-1]

            self.remove_worker(
                removable
            )

            event = {

                "timestamp":
                    datetime.utcnow()
                    .isoformat(),

                "action":
                    "SCALE_DOWN",

                "worker":
                    removable,
            }

            self.scaling_history.append(
                event
            )

    # =================================================
    # Failover Loop
    # =================================================

    def failover_loop(
        self,
    ):

        while self.running:

            try:

                if (
                    self.failover_enabled
                ):

                    self.evaluate_failover()

                time.sleep(10)

            except Exception as e:

                print(
                    "[FAILOVER ERROR]",
                    e,
                )

    # =================================================
    # Evaluate Failover
    # =================================================

    def evaluate_failover(
        self,
    ):

        dead = self.cluster.dead_nodes

        for node_id in dead.keys():

            result = (
                self.cluster.failover(
                    node_id
                )
            )

            self.failover_history.append(
                result
            )

    # =================================================
    # Predictive Loop
    # =================================================

    def predictive_loop(
        self,
    ):

        while self.running:

            try:

                if (
                    self.predictive_enabled
                ):

                    self.predictive_analysis()

                time.sleep(15)

            except Exception as e:

                print(
                    "[PREDICTIVE ERROR]",
                    e,
                )

    # =================================================
    # Predictive Analysis
    # =================================================

    def predictive_analysis(
        self,
    ):

        recent_failures = (
            self.db.recent_failures(
                limit=20
            )
        )

        failure_count = len(
            recent_failures
        )

        # =================================================
        # survival pressure
        # =================================================

        metrics = {

            "survival_score":
                max(
                    0.1,
                    1.0 -
                    (failure_count * 0.05)
                ),

            "volatility":
                min(
                    1.0,
                    failure_count * 0.05
                ),

            "drawdown":
                min(
                    1.0,
                    failure_count * 0.03
                ),

            "confidence":
                max(
                    0.1,
                    1.0 -
                    (failure_count * 0.04)
                ),
        }

        decision = (
            self.executive.decide(
                metrics
            )
        )

        # =================================================
        # emergency response
        # =================================================

        if decision[
            "action"
        ] == "EMERGENCY_STOP":

            self.alerts.emit(

                level="CRITICAL",

                title=(
                    "PREDICTIVE COLLAPSE"
                ),

                message=(
                    "system predicted "
                    "collapse"
                ),
            )

        # =================================================
        # retraining response
        # =================================================

        elif decision[
            "action"
        ] == "RETRAIN":

            self.create_worker(
                "RECOVERY"
            )

        self.db.save_snapshot(

            state_type=
                "PREDICTIVE_ANALYSIS",

            payload=decision,
        )

    # =================================================
    # Route Task
    # =================================================

    def route_task(

        self,

        task_type,
        target,
        payload=None,
    ):

        route = (
            self.cluster
            .route_task(
                task_type
            )
        )

        if not route:

            return None

        node_id = route[
            "node_id"
        ]

        if node_id not in (
            self.workers
        ):

            return None

        worker = self.workers[
            node_id
        ]

        task_id = (
            worker.submit_task(

                task_type=
                    task_type,

                target=
                    target,

                payload=
                    payload,
            )
        )

        self.routing_history.append({

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "task_id":
                task_id,

            "node":
                node_id,
        })

        return {

            "task_id":
                task_id,

            "worker":
                node_id,
        }

    # =================================================
    # Summary
    # =================================================

    def summary(
        self,
    ):

        return {

            "running":
                self.running,

            "workers":
                len(
                    self.workers
                ),

            "cluster":
                self.cluster.summary(),

            "scaling_events":
                len(
                    self.scaling_history
                ),

            "failovers":
                len(
                    self.failover_history
                ),

            "routes":
                len(
                    self.routing_history
                ),
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

            "workers": {

                wid:
                worker.status()

                for wid, worker
                in self.workers.items()
            },

            "cluster":
                self.cluster
                .diagnostics(),
        }


# =====================================================
# Example Tasks
# =====================================================

def compute_signal(
    x=0
):

    time.sleep(2)

    return {
        "signal": x * 2
    }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    orchestrator = (
        Orchestrator()
    )

    orchestrator.start()

    orchestrator.create_worker(
        "SCRAPER"
    )

    orchestrator.create_worker(
        "SIMULATION"
    )

    result = (
        orchestrator.route_task(

            task_type=
                "SIGNAL",

            target=
                compute_signal,

            payload={
                "x": 21
            },
        )
    )

    print(result)

    time.sleep(10)

    print(
        orchestrator.summary()
    )

    print(
        orchestrator.diagnostics()
    )

    orchestrator.stop()