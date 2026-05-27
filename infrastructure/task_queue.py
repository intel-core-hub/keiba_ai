# infrastructure/task_queue.py

import os
import json
import uuid
import queue
import threading
import traceback

from datetime import datetime
from concurrent.futures import (
    ThreadPoolExecutor
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


class TaskQueue:
    """
    Asynchronous Survival Infrastructure

    目的:
    - parallel execution
    - background survival tasks
    - non-blocking intelligence
    - resilient orchestration

    最重要:
    「止まらずに複数活動する」
    """

    def __init__(

        self,

        workers=4,
        queue_size=1000,
    ):

        self.workers = workers

        self.queue_size = queue_size

        # =================================================
        # queue
        # =================================================

        self.task_queue = queue.Queue(
            maxsize=queue_size
        )

        # =================================================
        # execution pool
        # =================================================

        self.executor = (
            ThreadPoolExecutor(
                max_workers=workers
            )
        )

        # =================================================
        # state
        # =================================================

        self.running = False

        self.active_tasks = {}

        self.completed_tasks = {}

        self.failed_tasks = {}

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

        self.persistence_path = (
            "infrastructure/task_queue_state.json"
        )

        os.makedirs(
            "infrastructure",
            exist_ok=True,
        )

    # =================================================
    # Start Workers
    # =================================================

    def start(
        self,
    ):

        if self.running:
            return

        self.running = True

        for _ in range(self.workers):

            thread = threading.Thread(

                target=self.worker_loop,

                daemon=True,
            )

            thread.start()

        self.audit.log(

            category="QUEUE",

            action="START",

            severity="INFO",
        )

        print(
            "[TASK QUEUE STARTED]"
        )

    # =================================================
    # Stop Workers
    # =================================================

    def stop(
        self,
    ):

        self.running = False

        self.executor.shutdown(
            wait=False
        )

        self.save_state()

        self.audit.log(

            category="QUEUE",

            action="STOP",

            severity="WARNING",
        )

        print(
            "[TASK QUEUE STOPPED]"
        )

    # =================================================
    # Add Task
    # =================================================

    def submit(

        self,

        task_type,
        target,
        payload=None,
        priority=5,
    ):

        task_id = str(
            uuid.uuid4()
        )

        task = {

            "id":
                task_id,

            "task_type":
                task_type,

            "target":
                target,

            "payload":
                payload or {},

            "priority":
                priority,

            "status":
                "PENDING",

            "created_at":
                datetime.utcnow()
                .isoformat(),
        }

        self.task_queue.put(task)

        with self.lock:

            self.active_tasks[
                task_id
            ] = task

        self.audit.log(

            category="QUEUE",

            action="SUBMIT_TASK",

            severity="INFO",

            metadata=task,
        )

        return task_id

    # =================================================
    # Worker Loop
    # =================================================

    def worker_loop(
        self,
    ):

        while self.running:

            try:

                task = (
                    self.task_queue.get(
                        timeout=1
                    )
                )

            except queue.Empty:
                continue

            future = (
                self.executor.submit(
                    self.execute_task,
                    task
                )
            )

            future.add_done_callback(

                lambda f,
                t=task:
                self.finalize_task(
                    t,
                    f
                )
            )

    # =================================================
    # Execute Task
    # =================================================

    def execute_task(

        self,

        task,
    ):

        task["status"] = (
            "RUNNING"
        )

        task["started_at"] = (
            datetime.utcnow()
            .isoformat()
        )

        try:

            target = task["target"]

            payload = task[
                "payload"
            ]

            # =============================================
            # callable task
            # =============================================

            if callable(target):

                result = target(
                    **payload
                )

            else:

                raise Exception(
                    "invalid target"
                )

            task["status"] = (
                "COMPLETED"
            )

            task["result"] = result

            task["completed_at"] = (
                datetime.utcnow()
                .isoformat()
            )

            return task

        except Exception as e:

            task["status"] = (
                "FAILED"
            )

            task["error"] = str(e)

            task["traceback"] = (
                traceback.format_exc()
            )

            task["failed_at"] = (
                datetime.utcnow()
                .isoformat()
            )

            return task

    # =================================================
    # Finalize Task
    # =================================================

    def finalize_task(

        self,

        original_task,
        future,
    ):

        try:

            result_task = (
                future.result()
            )

        except Exception as e:

            result_task = {

                "id":
                    original_task["id"],

                "status":
                    "FAILED",

                "error":
                    str(e),
            }

        task_id = result_task["id"]

        with self.lock:

            self.active_tasks.pop(
                task_id,
                None
            )

            if (
                result_task["status"]
                == "COMPLETED"
            ):

                self.completed_tasks[
                    task_id
                ] = result_task

            else:

                self.failed_tasks[
                    task_id
                ] = result_task

        # =================================================
        # persistence
        # =================================================

        self.persist_task(
            result_task
        )

        # =================================================
        # alert on failure
        # =================================================

        if (
            result_task["status"]
            == "FAILED"
        ):

            self.alerts.emit(

                level="ERROR",

                title=(
                    "TASK FAILURE"
                ),

                message=(
                    result_task.get(
                        "error"
                    )
                ),
            )

        self.audit.log(

            category="QUEUE",

            action=(
                result_task["status"]
            ),

            severity=(
                "ERROR"

                if result_task[
                    "status"
                ] == "FAILED"

                else "INFO"
            ),

            metadata=result_task,
        )

    # =================================================
    # Persist Task
    # =================================================

    def persist_task(

        self,

        task,
    ):

        self.db.insert(

            "audit_logs",

            {

                "timestamp":
                    datetime.utcnow()
                    .isoformat(),

                "category":
                    "TASK",

                "action":
                    task["status"],

                "severity":
                    (
                        "ERROR"

                        if task[
                            "status"
                        ] == "FAILED"

                        else "INFO"
                    ),

                "metadata":
                    json.dumps(
                        task,
                        default=str
                    ),
            }
        )

    # =================================================
    # Save Queue State
    # =================================================

    def save_state(
        self,
    ):

        payload = {

            "saved_at":
                datetime.utcnow()
                .isoformat(),

            "active":
                self.active_tasks,

            "completed":
                self.completed_tasks,

            "failed":
                self.failed_tasks,
        }

        with open(

            self.persistence_path,

            "w",

            encoding="utf-8",
        ) as f:

            json.dump(

                payload,

                f,

                indent=2,

                ensure_ascii=False,
                default=str,
            )

    # =================================================
    # Load Queue State
    # =================================================

    def load_state(
        self,
    ):

        if not os.path.exists(
            self.persistence_path
        ):

            return None

        with open(

            self.persistence_path,

            "r",

            encoding="utf-8",
        ) as f:

            payload = json.load(
                f
            )

        self.completed_tasks = (
            payload.get(
                "completed",
                {}
            )
        )

        self.failed_tasks = (
            payload.get(
                "failed",
                {}
            )
        )

        return payload

    # =================================================
    # Retry Failed Tasks
    # =================================================

    def retry_failed(
        self,
    ):

        retried = 0

        failed = list(
            self.failed_tasks.values()
        )

        for task in failed:

            if (
                "target"
                not in task
            ):

                continue

            self.submit(

                task_type=task[
                    "task_type"
                ],

                target=task[
                    "target"
                ],

                payload=task.get(
                    "payload",
                    {}
                ),
            )

            retried += 1

        return retried

    # =================================================
    # Queue Status
    # =================================================

    def status(
        self,
    ):

        return {

            "running":
                self.running,

            "workers":
                self.workers,

            "queued":
                self.task_queue.qsize(),

            "active":
                len(
                    self.active_tasks
                ),

            "completed":
                len(
                    self.completed_tasks
                ),

            "failed":
                len(
                    self.failed_tasks
                ),
        }

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "status":
                self.status(),

            "persistence":
                self.persistence_path,

            "db":
                self.db.diagnostics(),
        }


# =====================================================
# Example Tasks
# =====================================================

def sample_task(
    x=0,
    y=0,
):

    return {
        "result": x + y
    }


def failing_task():

    raise Exception(
        "intentional failure"
    )


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    queue_system = (
        TaskQueue(
            workers=3
        )
    )

    queue_system.start()

    queue_system.submit(

        task_type="MATH",

        target=sample_task,

        payload={
            "x": 10,
            "y": 20,
        },
    )

    queue_system.submit(

        task_type="FAIL",

        target=failing_task,
    )

    import time

    time.sleep(3)

    print(
        queue_system.status()
    )

    print(
        queue_system.diagnostics()
    )

    queue_system.stop()