#!/usr/bin/env python
"""Shadow-mode runner: predict, log bets.csv, never submit votes.

Usage:
    python scripts/shadow_accumulate.py --races 50

Set SHADOW_MODE=1 or shadow_mode: true in config/settings.yaml.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SHADOW_MODE", "1")
os.environ.setdefault("SAFE_MODE", "1")

from core.execution.calibration_refit import CalibrationRefitJob
from core.betting.decision_engine import DecisionEngine
from core.execution.bet_executor import BetExecutor
from core.prediction.calibration import ProbabilityCalibrator
from core.prediction.edge_calculator import EdgeCalculator
from core import BetSizer, Predictor, RiskManager
from execution.phase2_loop import Phase2OperationalLoop
from learning.performance_analyzer import PerformanceAnalyzer


def _shadow_odds_confirmer(bet_info: dict) -> float:
    """Simulate post-bet market drift for slippage monitoring during shadow runs."""
    predicted = float(bet_info["predicted_odds"])
    drift = random.uniform(-0.08, 0.05)
    return round(max(1.01, predicted * (1.0 + drift)), 4)


def build_loop(bets_log_path: str = "logs/bets.csv") -> Phase2OperationalLoop:
    risk = RiskManager()
    calibrator = CalibrationRefitJob(auto_refit_enabled=False).load_calibrator(ProbabilityCalibrator())
    engine = DecisionEngine(
        predictor=Predictor(),
        bet_sizer=BetSizer(risk_manager=risk),
        risk_manager=risk,
        edge_calculator=EdgeCalculator(),
        calibrator=calibrator,
    )
    calibration_job = CalibrationRefitJob(
        bets_log_path=bets_log_path,
        auto_refit_enabled=True,
    )

    def on_settle(_row: dict) -> None:
        calibration_job.record_new_settlement(1)
        calibration_job.maybe_refit()

    executor = BetExecutor(
        risk_manager=risk,
        log_path=bets_log_path,
        shadow_mode=True,
        safe_mode=True,
        odds_confirmer=_shadow_odds_confirmer,
        on_settle=on_settle,
    )

    return Phase2OperationalLoop(
        decision_engine=engine,
        bet_executor=executor,
        calibration_job=calibration_job,
        bets_log_path=bets_log_path,
    )


def _random_race(race_idx: int) -> tuple[str, list[dict], dict[str, bool]]:
    race_id = f"SHADOW_{race_idx:04d}"
    horses = []
    for i in range(random.randint(8, 14)):
        horses.append(
            {
                "selection": f"H{i}",
                "odds": round(random.uniform(1.5, 25.0), 2),
                "features": {},
            }
        )
    winner = random.choice(horses)["selection"]
    outcomes = {h["selection"]: h["selection"] == winner for h in horses}
    return race_id, horses, outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description="Shadow-mode bet log accumulation")
    parser.add_argument("--races", type=int, default=300, help="Number of synthetic races")
    parser.add_argument("--bets-log", default="logs/bets.csv", help="Path to bets.csv")
    args = parser.parse_args()

    loop = build_loop(args.bets_log)
    settled = 0

    for idx in range(args.races):
        race_id, candidates, outcomes = _random_race(idx)
        decisions = loop.decide_race(race_id, candidates)
        if not decisions:
            continue
        loop.settle_race(race_id, decisions, outcomes, regime="SHADOW")
        settled += len(decisions)

    metrics = loop.phase2_metrics()
    readiness = {}
    if Path(args.bets_log).exists():
        readiness = PerformanceAnalyzer().analyze(args.bets_log).get("phase1_readiness", {})
    print(f"Shadow run complete. settled_bets={settled}")
    print(f"Reliability recommendation: {metrics.get('reliability_recommendation')}")
    print(f"Calibration: {loop.calibration_job.last_result if loop.calibration_job else 'n/a'}")
    print(f"Phase 1 readiness: {readiness}")


if __name__ == "__main__":
    main()
