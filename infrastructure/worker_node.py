# infrastructure/worker_node.py

import os
import json
import time
import uuid
import socket
import traceback
import threading

from datetime import datetime

from infrastructure.task_queue import (
    TaskQueue
)

from infrastructure.database import (
    SurvivalDatabase
)

from core.audit_logger import (
    AuditLogger
)

from core.alert_manager import (
    AlertManager
)


class WorkerNode:
    """
    Distributed Survival Worker

    目的:
    - distributed execution
    - fault isolation
    - resilient task handling
    - partial survival

    最重要:
    「壊れても全体は死なない」
    """

    def __init__(

        self,

        node_type="GENERAL",

        heartbeat_interval=5,
    ):

        # =================================================
        # identity
        # =================================================

        self.node_id = str(
            uuid.uuid4()
        )

        self.node_type = (
            node_type
        )

        self.hostname = (
            socket.gethostname()
        )

        # =================================================
        # runtime
        # =================================================

        self.running = False

        self.started_at = None

        self.last_heartbeat = None

        self.heartbeat_interval = (
            heartbeat_interval
        )

        # =================================================
        # metrics
        # =================================================

        self.tasks_completed = 0

        self.tasks_failed = 0

        self.restarts = 0

        self.total_runtime = 0

        # =================================================
        # infrastructure
        # =================================================

        self.queue = (
            TaskQueue()
        )

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

        self.state_path = (
            f"infrastructure/"
            f"worker_{self.node_id}.json"
        )

        os.makedirs(
            "infrastructure",
            exist_ok=True,
        )

    # =================================================
    # Start Worker
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

        self.queue.start()

        # =================================================
        # heartbeat thread
        # =================================================

        heartbeat_thread = (
            threading.Thread(

                target=self.heartbeat_loop,

                daemon=True,
            )
        )

        heartbeat_thread.start()

        # =================================================
        # monitoring thread
        # =================================================

        monitor_thread = (
            threading.Thread(

                target=self.monitor_loop,

                daemon=True,
            )
        )

        monitor_thread.start()

        self.audit.log(

            category="WORKER",

            action="START",

            severity="INFO",

            metadata=self.identity(),
        )

        print(
            f"[WORKER STARTED] "
            f"{self.node_id}"
        )

    # =================================================
    # Stop Worker
    # =================================================

    def stop(
        self,
    ):

        self.running = False

        self.queue.stop()

        self.persist_state()

        self.audit.log(

            category="WORKER",

            action="STOP",

            severity="WARNING",

            metadata=self.identity(),
        )

        print(
            f"[WORKER STOPPED] "
            f"{self.node_id}"
        )

    # =================================================
    # Heartbeat
    # =================================================

    def heartbeat_loop(
        self,
    ):

        while self.running:

            try:

                self.last_heartbeat = (
                    datetime.utcnow()
                    .isoformat()
                )

                self.db.insert(

                    "state_snapshots",

                    {

                        "timestamp":
                            self.last_heartbeat,

                        "state_type":
                            "HEARTBEAT",

                        "payload":
                            json.dumps(
                                self.identity()
                            ),
                    }
                )

                time.sleep(
                    self.heartbeat_interval
                )

            except Exception as e:

                print(
                    "[HEARTBEAT ERROR]",
                    e,
                )

    # =================================================
    # Monitoring Loop
    # =================================================

    def monitor_loop(
        self,
    ):

        while self.running:

            try:

                status = (
                    self.queue.status()
                )

                failed = status[
                    "failed"
                ]

                # =============================================
                # high failure detection
                # =============================================

                if failed >= 10:

                    self.alerts.emit(

                        level="CRITICAL",

                        title=(
                            "WORKER FAILURE"
                        ),

                        message=(
                            f"{failed} "
                            f"task failures"
                        ),
                    )

                # =============================================
                # auto retry
                # =============================================

                if failed > 0:

                    retried = (
                        self.queue
                        .retry_failed()
                    )

                    if retried > 0:

                        self.audit.log(

                            category="WORKER",

                            action=(
                                "RETRY_FAILED"
                            ),

                            severity="WARNING",

                            metadata={
                                "retried":
                                    retried
                            },
                        )

                time.sleep(10)

            except Exception as e:

                print(
                    "[MONITOR ERROR]",
                    e,
                )

    # =================================================
    # Submit Task
    # =================================================

    def submit_task(

        self,

        task_type,
        target,
        payload=None,
        priority=5,
    ):

        return self.queue.submit(

            task_type=task_type,

            target=target,

            payload=payload,

            priority=priority,
        )

    # =================================================
    # Execute Safe
    # =================================================

    def execute_safe(

        self,

        target,
        payload=None,
    ):

        try:

            result = target(
                **(payload or {})
            )

            self.tasks_completed += 1

            return {

                "success":
                    True,

                "result":
                    result,
            }

        except Exception as e:

            self.tasks_failed += 1

            self.audit.log(

                category="WORKER",

                action="EXECUTION_ERROR",

                severity="ERROR",

                metadata={
                    "error":
                        str(e),

                    "traceback":
                        traceback
                        .format_exc(),
                },
            )

            return {

                "success":
                    False,

                "error":
                    str(e),
            }

    # =================================================
    # Persist State
    # =================================================

    def persist_state(
        self,
    ):

        payload = {

            "node_id":
                self.node_id,

            "node_type":
                self.node_type,

            "hostname":
                self.hostname,

            "running":
                self.running,

            "started_at":
                self.started_at,

            "last_heartbeat":
                self.last_heartbeat,

            "tasks_completed":
                self.tasks_completed,

            "tasks_failed":
                self.tasks_failed,

            "restarts":
                self.restarts,

            "saved_at":
                datetime.utcnow()
                .isoformat(),
        }

        with open(

            self.state_path,

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
    # Load State
    # =================================================

    def load_state(
        self,
    ):

        if not os.path.exists(
            self.state_path
        ):

            return None

        with open(

            self.state_path,

            "r",

            encoding="utf-8",
        ) as f:

            payload = json.load(
                f
            )

        self.tasks_completed = (
            payload.get(
                "tasks_completed",
                0,
            )
        )

        self.tasks_failed = (
            payload.get(
                "tasks_failed",
                0,
            )
        )

        self.restarts = (
            payload.get(
                "restarts",
                0,
            )
        )

        return payload

    # =================================================
    # Restart
    # =================================================

    def restart(
        self,
    ):

        self.stop()

        time.sleep(1)

        self.restarts += 1

        self.start()

        self.audit.log(

            category="WORKER",

            action="RESTART",

            severity="WARNING",
        )

    # =================================================
    # Identity
    # =================================================

    def identity(
        self,
    ):

        return {

            "node_id":
                self.node_id,

            "node_type":
                self.node_type,

            "hostname":
                self.hostname,

            "running":
                self.running,

            "last_heartbeat":
                self.last_heartbeat,
        }

    # =================================================
    # Status
    # =================================================

    def status(
        self,
    ):

        uptime = 0

        if self.started_at:

            started = datetime.fromisoformat(
                self.started_at
            )

            uptime = (
                datetime.utcnow()
                - started
            ).total_seconds()

        return {

            "identity":
                self.identity(),

            "uptime_seconds":
                uptime,

            "tasks_completed":
                self.tasks_completed,

            "tasks_failed":
                self.tasks_failed,

            "restarts":
                self.restarts,

            "queue":
                self.queue.status(),
        }

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "worker":
                self.status(),

            "database":
                self.db.diagnostics(),

            "queue":
                self.queue.diagnostics(),
        }


# =====================================================
# Example Tasks
# =====================================================

def scrape_market(
    symbol="BTCUSDT"
):

    time.sleep(2)

    return {

        "symbol":
            symbol,

        "price":
            100000,
    }


def simulate_strategy(
    strategy="baseline"
):

    time.sleep(3)

    return {

        "strategy":
            strategy,

        "fitness":
            0.73,
    }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    worker = WorkerNode(
        node_type="SIMULATION"
    )

    worker.start()

    worker.submit_task(

        task_type="SCRAPE",

        target=scrape_market,

        payload={
            "symbol":
                "ETHUSDT"
        },
    )

    worker.submit_task(

        task_type="SIMULATION",

        target=simulate_strategy,

        payload={
            "strategy":
                "adaptive_v2"
        },
    )

    time.sleep(8)

    print(
        worker.status()
    )

    print(
        worker.diagnostics()
    )

    worker.stop()