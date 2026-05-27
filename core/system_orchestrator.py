"""
core/system_orchestrator.py

Consolidated SystemOrchestrator implementation (single definition).
"""

import os
import time
import traceback
import pandas as pd

from datetime import datetime

from scraping.netkeiba_scraper import (
    NetkeibaScraper
)

from data.historical_dataset import (
    HistoricalDatasetBuilder
)

from simulation.live_simulation import (
    LiveSimulation
)

ENABLE_RESEARCH = os.getenv("KEIBA_ENABLE_RESEARCH", "0") == "1"


class _NullAutoRetrainer:
    def recovery_cycle(self, regime_detector):
        return {
            "status": "SKIPPED",
            "reason": "research_disabled",
            "regime": getattr(regime_detector, "current_regime", "NORMAL"),
        }


if ENABLE_RESEARCH:
    try:
        from core.auto_retrainer import _load_autoretrainer
        AutoRetrainer = _load_autoretrainer()
    except Exception:
        AutoRetrainer = _NullAutoRetrainer
else:
    AutoRetrainer = _NullAutoRetrainer

from core.regime_detector import (
    RegimeDetector
)


class SystemOrchestrator:
    """
    Survival System Orchestrator

    目的:
    - 全体統合
    - 自動循環
    - self healing
    - survival automation

    最重要:
    「止まらず生き残る」
    """

    def __init__(

        self,

        loop_interval=3600,
    ):

        self.loop_interval = (
            loop_interval
        )

        # =================================================
        # systems
        # =================================================

        self.scraper = (
            NetkeibaScraper()
        )

        self.dataset_builder = (
            HistoricalDatasetBuilder()
        )

        self.retrainer = (
            AutoRetrainer()
        )

        self.regime_detector = (
            RegimeDetector()
        )

        # =================================================
        # state
        # =================================================

        self.running = False

        self.cycle_count = 0

        self.last_cycle = None

        self.last_error = None

        self.shutdown = False

        # =================================================
        # diagnostics
        # =================================================

        self.health_history = []

    # =================================================
    # Health Snapshot
    # =================================================

    def health_snapshot(
        self,
        status="OK",
    ):

        snapshot = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "cycle":
                self.cycle_count,

            "status":
                status,

            "regime":
                self.regime_detector
                .current_regime,

            "last_error":
                self.last_error,
        }

        self.health_history.append(
            snapshot
        )

        return snapshot

    # =================================================
    # Scraping Phase
    # =================================================

    def scraping_phase(
        self,
    ):

        print("\n====================")
        print("SCRAPING PHASE")
        print("====================")

        today = datetime.utcnow().strftime(
            "%Y%m%d"
        )

        # =================================================
        # scrape today
        # =================================================

        df = (
            self.scraper
            .scrape_date_range(

                start_date=today,

                end_date=today,
            )
        )

        if df is None:

            print(
                "[NO DATA]"
            )

            return None

        clean = (
            self.scraper
            .minimal_features(
                df
            )
        )

        path = (

            f"data/raw/"
            f"live_{today}.csv"
        )

        self.scraper.save_csv(

            clean,

            path,
        )

        return path

    # =================================================
    # Dataset Phase
    # =================================================

    def dataset_phase(
        self,
    ):

        print("\n====================")
        print("DATASET PHASE")
        print("====================")

        dataset = (
            self.dataset_builder
            .build()
        )

        return dataset

    # =================================================
    # Simulation Phase
    # =================================================

    def simulation_phase(
        self,
        dataset,
    ):

        print("\n====================")
        print("SIMULATION PHASE")
        print("====================")

        simulator = (
            LiveSimulation(

                bankroll=100000,

                min_edge=0.03,

                max_risk=0.02,
            )
        )

        result = simulator.run(
            dataset
        )

        # =================================================
        # sync regime
        # =================================================

        self.regime_detector.current_regime = (
            simulator.current_regime
        )

        return result

    # =================================================
    # Recovery Phase
    # =================================================

    def recovery_phase(
        self,
    ):

        print("\n====================")
        print("RECOVERY PHASE")
        print("====================")

        result = (
            self.retrainer
            .recovery_cycle(
                self.regime_detector,
            )
        )

        return result

    # =================================================
    # Survival Evaluation
    # =================================================

    def evaluate_survival(
        self,
        sim_result,
    ):

        survival = sim_result.get(
            "survival_score",
            0,
        )

        shutdown = sim_result.get(
            "shutdown",
            False,
        )

        # =================================================
        # emergency
        # =================================================

        if shutdown:

            print(
                "\n[EMERGENCY]"
            )

            self.shutdown = True

            return False

        # =================================================
        # low survival
        # =================================================

        if survival < 0.30:

            print(
                "\n[LOW SURVIVAL]"
            )

            self.regime_detector.current_regime = (
                "COLLAPSE"
            )

            return False

        return True

    # =================================================
    # Single Cycle
    # =================================================

    def run_cycle(
        self,
    ):

        print("\n\n")
        print("################################")
        print(
            f"CYCLE {self.cycle_count}"
        )
        print("################################")

        self.last_cycle = (
            datetime.utcnow()
            .isoformat()
        )

        try:

            # =================================================
            # health
            # =================================================

            self.health_snapshot(
                status="STARTING"
            )

            # =================================================
            # scraping
            # =================================================

            self.scraping_phase()

            # =================================================
            # dataset
            # =================================================

            dataset = (
                self.dataset_phase()
            )

            # =================================================
            # simulation
            # =================================================

            sim_result = (
                self.simulation_phase(
                    dataset
                )
            )

            # =================================================
            # evaluate
            # =================================================

            alive = (
                self.evaluate_survival(
                    sim_result
                )
            )

            # =================================================
            # recovery
            # =================================================

            if not alive:

                self.recovery_phase()

            # =================================================
            # health
            # =================================================

            self.health_snapshot(
                status="OK"
            )

            self.cycle_count += 1

            return {

                "status":
                    "SUCCESS",

                "simulation":
                    sim_result,
            }

        except Exception as e:

            self.last_error = str(e)

            print("\n[ORCHESTRATOR ERROR]")

            print(e)

            traceback.print_exc()

            self.health_snapshot(
                status="ERROR"
            )

            return {

                "status":
                    "ERROR",

                "error":
                    str(e),
            }

    # =================================================
    # Main Loop
    # =================================================

    def run_forever(
        self,
    ):

        print("\n====================")
        print("SURVIVAL OS START")
        print("====================")

        self.running = True

        while (

            self.running

            and not self.shutdown
        ):

            result = (
                self.run_cycle()
            )

            print("\n[CYCLE RESULT]")

            print(result)

            # =================================================
            # cooldown
            # =================================================

            print(
                "\n[SLEEP]"
            )

            print(
                self.loop_interval,
                "seconds"
            )

            time.sleep(
                self.loop_interval
            )

        print("\n====================")
        print("SYSTEM STOPPED")
        print("====================")

    # =================================================
    # Manual Stop
    # =================================================

    def stop(
        self,
    ):

        self.running = False

        print(
            "\n[STOP REQUESTED]"
        )

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "running":
                self.running,

            "shutdown":
                self.shutdown,

            "cycle_count":
                self.cycle_count,

            "last_cycle":
                self.last_cycle,

            "last_error":
                self.last_error,

            "regime":
                self.regime_detector
                .current_regime,

            "health_entries":
                len(
                    self.health_history
                ),
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    orchestrator = (
        SystemOrchestrator(

            loop_interval=60
        )
    )

    # =================================================
    # single cycle
    # =================================================

    result = (
        orchestrator.run_cycle()
    )

    print("\nFINAL RESULT")

    print(result)

    print("\nDIAGNOSTICS")

    print(
        orchestrator.diagnostics()
    )

    # =================================================
    # continuous mode
    # =================================================

    """
    orchestrator.run_forever()
    """