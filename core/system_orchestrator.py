"""Research-side orchestrator with explicit dependency injection.

The runtime tree can import this module safely because it does not name or import
offline implementations directly. Research-only dataset builders, simulators, and
retraining strategies must be injected by the caller.
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime
from typing import Any, Callable

from core.regime_detector import RegimeDetector
from scraping.netkeiba_scraper import NetkeibaScraper


class _NullAutoRetrainer:
    def recovery_cycle(self, regime_detector):
        return {
            "status": "SKIPPED",
            "reason": "research_dependency_missing",
            "regime": getattr(regime_detector, "current_regime", "NORMAL"),
        }


class SystemOrchestrator:
    """Research-side system loop kept outside the production critical path."""

    def __init__(
        self,
        loop_interval=3600,
        *,
        dataset_builder: Any = None,
        simulator_factory: Callable[..., Any] | None = None,
        retrainer: Any = None,
    ):
        self.loop_interval = loop_interval
        self.scraper = NetkeibaScraper()
        self.regime_detector = RegimeDetector()
        self.dataset_builder = dataset_builder
        self.simulator_factory = simulator_factory
        self.retrainer = retrainer or _NullAutoRetrainer()

        self.running = False
        self.cycle_count = 0
        self.last_cycle = None
        self.last_error = None
        self.shutdown = False
        self.health_history = []

    def _require_dependency(self, value: Any, feature_name: str) -> Any:
        if value is not None:
            return value
        raise RuntimeError(f"{feature_name} requires an injected research dependency.")

    def health_snapshot(self, status="OK"):
        snapshot = {
            "timestamp": datetime.utcnow().isoformat(),
            "cycle": self.cycle_count,
            "status": status,
            "regime": self.regime_detector.current_regime,
            "last_error": self.last_error,
        }
        self.health_history.append(snapshot)
        return snapshot

    def scraping_phase(self):
        print("\n====================")
        print("SCRAPING PHASE")
        print("====================")

        today = datetime.utcnow().strftime("%Y%m%d")
        df = self.scraper.scrape_date_range(start_date=today, end_date=today)
        if df is None:
            print("[NO DATA]")
            return None

        clean = self.scraper.minimal_features(df)
        path = f"data/raw/live_{today}.csv"
        self.scraper.save_csv(clean, path)
        return path

    def dataset_phase(self):
        print("\n====================")
        print("DATASET PHASE")
        print("====================")

        builder = self._require_dependency(self.dataset_builder, "dataset_phase")
        return builder.build()

    def simulation_phase(self, dataset):
        print("\n====================")
        print("SIMULATION PHASE")
        print("====================")

        simulator_factory = self._require_dependency(self.simulator_factory, "simulation_phase")
        simulator = simulator_factory(
            bankroll=100000,
            min_edge=0.03,
            max_risk=0.02,
        )
        result = simulator.run(dataset)
        self.regime_detector.current_regime = simulator.current_regime
        return result

    def recovery_phase(self):
        print("\n====================")
        print("RECOVERY PHASE")
        print("====================")
        return self.retrainer.recovery_cycle(self.regime_detector)

    def evaluate_survival(self, sim_result):
        survival = sim_result.get("survival_score", 0)
        shutdown = sim_result.get("shutdown", False)

        if shutdown:
            print("\n[EMERGENCY]")
            self.shutdown = True
            return False

        if survival < 0.30:
            print("\n[LOW SURVIVAL]")
            self.regime_detector.current_regime = "COLLAPSE"
            return False

        return True

    def run_cycle(self):
        print("\n\n")
        print("################################")
        print(f"CYCLE {self.cycle_count}")
        print("################################")

        self.last_cycle = datetime.utcnow().isoformat()

        try:
            self.health_snapshot(status="STARTING")
            self.scraping_phase()
            dataset = self.dataset_phase()
            sim_result = self.simulation_phase(dataset)
            alive = self.evaluate_survival(sim_result)

            if not alive:
                self.recovery_phase()

            self.health_snapshot(status="OK")
            self.cycle_count += 1
            return {
                "status": "SUCCESS",
                "simulation": sim_result,
            }
        except Exception as exc:
            self.last_error = str(exc)
            print("\n[ORCHESTRATOR ERROR]")
            print(exc)
            traceback.print_exc()
            self.health_snapshot(status="ERROR")
            return {
                "status": "ERROR",
                "error": str(exc),
            }

    def run_forever(self):
        print("\n====================")
        print("SURVIVAL OS START")
        print("====================")

        self.running = True
        while self.running and not self.shutdown:
            result = self.run_cycle()
            print("\n[CYCLE RESULT]")
            print(result)
            print("\n[SLEEP]")
            print(self.loop_interval, "seconds")
            time.sleep(self.loop_interval)

        print("\n====================")
        print("SYSTEM STOPPED")
        print("====================")

    def stop(self):
        self.running = False
        print("\n[STOP REQUESTED]")

    def diagnostics(self):
        return {
            "running": self.running,
            "shutdown": self.shutdown,
            "cycle_count": self.cycle_count,
            "last_cycle": self.last_cycle,
            "last_error": self.last_error,
            "regime": self.regime_detector.current_regime,
            "health_entries": len(self.health_history),
        }


if __name__ == "__main__":
    orchestrator = SystemOrchestrator(loop_interval=60)
    result = orchestrator.run_cycle()
    print("\nFINAL RESULT")
    print(result)
    print("\nDIAGNOSTICS")
    print(orchestrator.diagnostics())
