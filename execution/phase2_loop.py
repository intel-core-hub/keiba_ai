import csv
import os
from datetime import datetime
from typing import Any, Optional

from learning.performance_analyzer import PerformanceAnalyzer
from learning.reliability_curve import ReliabilityCurveAnalyzer


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
        bets_log_path="logs/bets.csv",
    ):

        self.engine = decision_engine
        self.reliability = reliability_analyzer or ReliabilityCurveAnalyzer()
        self.performance = performance_analyzer or PerformanceAnalyzer()
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
            else:
                self._append_bet_log(
                    race_id=race_id,
                    decision=d,
                    hit=hit,
                    profit=profit,
                    bankroll=float(self.engine.risk_manager.bankroll),
                    regime=regime,
                )

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

    def _append_bet_log(self, race_id, decision, hit, profit, bankroll, regime):

        os.makedirs(os.path.dirname(self.bets_log_path), exist_ok=True)

        file_exists = os.path.exists(self.bets_log_path)

        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "race_id": race_id,
            "selection": decision.selection,
            "odds": round(float(decision.odds), 4),
            "stake": int(decision.bet_size),
            "probability": round(float(decision.calibrated_probability), 6),
            "raw_probability": round(float(decision.probability), 6),
            "market_probability": round(float(decision.market_probability), 6),
            "expected_value": round(float(decision.expected_value), 6),
            "edge": round(float(decision.edge), 6),
            "edge_quality": round(float(decision.edge_quality), 6),
            "uncertainty_score": round(float(decision.uncertainty_score), 6),
            "hit": int(bool(hit)),
            "profit": round(float(profit), 4),
            "bankroll": round(float(bankroll), 2),
            "regime": regime,
        }

        fields = list(row.keys())

        with open(self.bets_log_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
