import os
from datetime import datetime
from typing import Any, Optional


class RuntimeReliabilityAnalyzer:
    """Small in-memory reliability tracker for runtime status only."""

    def __init__(self) -> None:
        self.records = []

    def record(self, probability, hit) -> None:
        self.records.append((float(probability), int(hit)))
        self.records = self.records[-5000:]

    def analyze(self) -> dict[str, Any]:
        if not self.records:
            return {"error": "no data"}
        brier = sum((prob - hit) ** 2 for prob, hit in self.records) / len(self.records)
        hit_rate = sum(hit for _, hit in self.records) / len(self.records)
        return {
            "brier": round(float(brier), 4),
            "hit_rate": round(float(hit_rate), 4),
            "samples": len(self.records),
        }

    def recommendation(self) -> dict[str, str]:
        analysis = self.analyze()
        if "error" in analysis:
            return {"action": "NO_BET", "reason": "missing_reliability_samples"}
        if float(analysis["brier"]) > 0.22:
            return {"action": "NO_BET", "reason": "calibration_invalid"}
        return {"action": "MONITOR", "reason": "runtime_reliability_ok"}


class RuntimePerformanceAnalyzer:
    """Runtime placeholder; detailed pandas analysis is offline-only."""

    def analyze(self, path="derived/bets.csv") -> dict[str, Any]:
        return {"status": "offline_only", "path": path}


class Phase2OperationalLoop:
    """
    Minimal production loop:
    prediction -> calibration -> EV -> risk -> execution -> feedback
    """

    def __init__(
        self,
        decision_engine,
        validator_report=None,
        reliability_analyzer=None,
        performance_analyzer=None,
        bet_executor=None,
        calibration_job=None,
        bets_log_path="derived/bets.csv",
    ):

        self.engine = decision_engine
        self.reliability = reliability_analyzer or RuntimeReliabilityAnalyzer()
        self.performance = performance_analyzer or RuntimePerformanceAnalyzer()
        self.bet_executor = bet_executor
        self.calibration_job = calibration_job
        self.bets_log_path = bets_log_path

        self.last_validator_report = {}
        self.last_decisions = []

        if validator_report:
            self.apply_validator_report(validator_report)

    def apply_validator_report(self, report):

        if not isinstance(report, dict):
            return

        self.last_validator_report = report

        calibration_state = {
            "mean_brier": report.get("mean_brier", report.get("brier_mean")),
            "mean_ece": report.get("mean_ece", report.get("ece_mean")),
            "mean_reliability": report.get("mean_reliability", report.get("reliability_mean")),
            "drift_score": report.get("drift_score", report.get("stability", {}).get("drift_score") if isinstance(report.get("stability", {}), dict) else None),
        }

        self.engine.set_calibration_state(calibration_state)

    def decide_race(self, race_id, candidates):

        decisions = self.engine.decide_race(race_id, candidates)
        self.last_decisions = decisions

        if self.bet_executor is not None:
            for decision in decisions:
                self.bet_executor.execute_bet(decision)

        return decisions

    def settle_race(self, race_id, decisions, outcome_by_selection, regime="UNKNOWN"):

        outcomes = []

        for d in decisions:
            hit = bool(outcome_by_selection.get(d.selection, False))
            profit = float(self.engine.update_result(d, hit=hit))

            self.reliability.record(
                probability=float(d.calibrated_probability),
                hit=int(hit),
            )

            if self.bet_executor is not None:
                self.bet_executor.update_result(d, hit=hit, profit=profit)
                if self.calibration_job is not None:
                    self.calibration_job.record_new_settlement(1)

            outcomes.append({
                "race_id": race_id,
                "selection": d.selection,
                "hit": hit,
                "profit": round(profit, 4),
            })

        return outcomes

    def phase2_metrics(self):

        reliability = self.reliability.analyze()
        recommendation = self.reliability.recommendation()

        perf = self.performance.analyze(self.bets_log_path) if os.path.exists(self.bets_log_path) else {}

        calibration_result = None
        if self.calibration_job is not None:
            calibration_result = self.calibration_job.maybe_refit(
                reliability_analyzer=self.reliability,
            )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "validator": self.last_validator_report,
            "reliability": reliability,
            "reliability_recommendation": recommendation,
            "calibration_refit": calibration_result,
            "performance": perf,
            "risk": self.engine.risk_manager.status(),
        }
