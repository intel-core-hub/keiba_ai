# core/scheduler.py

import time
import traceback
import schedule

from datetime import datetime

from core.system_orchestrator import (
    SystemOrchestrator
)

from core.state_manager import (
    StateManager
)

from core.alert_manager import (
    AlertManager
)


class SurvivalScheduler:
    """
    Autonomous Scheduler

    目的:
    - 時間駆動
    - event automation
    - scheduled recovery
    - continuous survival

    最重要:
    「止まらず循環する」
    """

    def __init__(
        self,
    ):

        # =================================================
        # systems
        # =================================================

        self.orchestrator = (
            SystemOrchestrator()
        )

        self.state_manager = (
            StateManager()
        )

        self.alerts = (
            AlertManager()
        )

        # =================================================
        # scheduler state
        # =================================================

        self.running = False

        self.last_tick = None

        self.job_history = []

        # =================================================
        # restore previous state
        # =================================================

        self.restore_state()

        # =================================================
        # register jobs
        # =================================================

        self.register_jobs()

    # =================================================
    # Restore
    # =================================================

    def restore_state(
        self,
    ):

        try:

            self.state_manager.restore(

                orchestrator=(
                    self.orchestrator
                ),

                detector=(
                    self.orchestrator
                    .regime_detector
                ),
            )

            print(
                "[STATE RESTORED]"
            )

        except Exception as e:

            print(
                "[RESTORE ERROR]",
                e,
            )

    # =================================================
    # Job Wrapper
    # =================================================

    def safe_job(

        self,

        name,
        fn,
    ):

        def wrapped():

            started = (
                datetime.utcnow()
                .isoformat()
            )

            print("\n====================")
            print(f"JOB: {name}")
            print("====================")

            try:

                result = fn()

                self.job_history.append({

                    "job":
                        name,

                    "status":
                        "SUCCESS",

                    "timestamp":
                        started,
                })

                return result

            except Exception as e:

                print(
                    "[JOB ERROR]",
                    e,
                )

                traceback.print_exc()

                self.job_history.append({

                    "job":
                        name,

                    "status":
                        "ERROR",

                    "timestamp":
                        started,

                    "error":
                        str(e),
                })

                self.alerts.exception(

                    e,

                    context={
                        "job":
                            name
                    },
                )

                return None

        return wrapped

    # =================================================
    # Main Survival Cycle
    # =================================================

    def survival_cycle(
        self,
    ):

        result = (
            self.orchestrator
            .run_cycle()
        )

        # =================================================
        # alerts
        # =================================================

        simulation = result.get(
            "simulation",
            {},
        )

        if simulation:

            self.alerts.check_survival(

                survival_score=(
                    simulation.get(
                        "survival_score",
                        1,
                    )
                ),

                drawdown=0,

                regime=(
                    simulation.get(
                        "regime",
                        "NORMAL",
                    )
                ),
            )

        # =================================================
        # persistence
        # =================================================

        self.snapshot()

        return result

    # =================================================
    # Snapshot
    # =================================================

    def snapshot(
        self,
    ):

        self.state_manager.snapshot(

            orchestrator=(
                self.orchestrator
            ),

            detector=(
                self.orchestrator
                .regime_detector
            ),
        )

    # =================================================
    # Diagnostics Job
    # =================================================

    def diagnostics_job(
        self,
    ):

        diag = (
            self.orchestrator
            .diagnostics()
        )

        print("\n[DIAGNOSTICS]")

        print(diag)

        return diag

    # =================================================
    # Recovery Job
    # =================================================

    def recovery_job(
        self,
    ):

        result = (

            self.orchestrator
            .recovery_phase()
        )

        self.alerts.recovery(
            result
        )

        return result

    # =================================================
    # Register Jobs
    # =================================================

    def register_jobs(
        self,
    ):

        # =================================================
        # frequent diagnostics
        # =================================================

        schedule.every(10).minutes.do(

            self.safe_job(

                "diagnostics",

                self.diagnostics_job,
            )
        )

        # =================================================
        # periodic snapshot
        # =================================================

        schedule.every(15).minutes.do(

            self.safe_job(

                "snapshot",

                self.snapshot,
            )
        )

        # =================================================
        # survival cycle
        # =================================================

        schedule.every(1).hours.do(

            self.safe_job(

                "survival_cycle",

                self.survival_cycle,
            )
        )

        # =================================================
        # nightly recovery
        # =================================================

        schedule.every().day.at(
            "03:00"
        ).do(

            self.safe_job(

                "nightly_recovery",

                self.recovery_job,
            )
        )

        print(
            "[JOBS REGISTERED]"
        )

    # =================================================
    # Tick
    # =================================================

    def tick(
        self,
    ):

        self.last_tick = (
            datetime.utcnow()
            .isoformat()
        )

        schedule.run_pending()

    # =================================================
    # Main Loop
    # =================================================

    def run_forever(
        self,
    ):

        print("\n====================")
        print("SURVIVAL SCHEDULER")
        print("====================")

        self.running = True

        while self.running:

            try:

                self.tick()

                time.sleep(1)

            except KeyboardInterrupt:

                print(
                    "\n[KEYBOARD STOP]"
                )

                self.stop()

            except Exception as e:

                print(
                    "\n[LOOP ERROR]",
                    e,
                )

                traceback.print_exc()

                self.alerts.exception(

                    e,

                    context={
                        "loop":
                            True
                    },
                )

                time.sleep(10)

    # =================================================
    # Stop
    # =================================================

    def stop(
        self,
    ):

        self.running = False

        # =================================================
        # final snapshot
        # =================================================

        self.snapshot()

        print(
            "\n[SCHEDULER STOPPED]"
        )

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        jobs = []

        for job in schedule.jobs:

            jobs.append({

                "job":
                    str(job),

                "next_run":
                    str(
                        job.next_run
                    ),
            })

        return {

            "running":
                self.running,

            "last_tick":
                self.last_tick,

            "jobs":
                jobs,

            "job_history":
                (
                    self.job_history[-20:]
                ),
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    scheduler = (
        SurvivalScheduler()
    )

    print(
        scheduler.diagnostics()
    )

    scheduler.run_forever()