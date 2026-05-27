from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

from core.ruin_probability import RuinProbabilityEstimator
from core.survival_metrics import SurvivalMetricsSystem


@dataclass
class StressScenario:
    name: str
    profit_scale: float = 1.0
    loss_scale: float = 1.0
    stake_scale: float = 1.0
    exposure_scale: float = 1.0
    uncertainty_penalty: float = 0.0
    calibration_penalty: float = 0.0


class StressTestEngine:
    """Explainable stress tester for collapse risk and resilience."""

    def __init__(self, ruin_threshold: float = 0.3):
        self.ruin_threshold = float(ruin_threshold)
        self.survival = SurvivalMetricsSystem()
        self.ruin_estimator = RuinProbabilityEstimator()

    def default_scenarios(self) -> List[StressScenario]:
        return [
            StressScenario("baseline", 1.0, 1.0, 1.0, 1.0, 0.0, 0.0),
            StressScenario("aggressive", 1.15, 1.10, 1.25, 1.30, 0.02, 0.01),
            StressScenario("defensive", 0.92, 1.00, 0.70, 0.65, 0.00, 0.00),
            StressScenario("uncertainty_storm", 0.78, 1.12, 1.00, 0.95, 0.12, 0.05),
            StressScenario("calibration_deterioration", 0.82, 1.08, 1.00, 1.00, 0.00, 0.12),
            StressScenario("exposure_crunch", 0.88, 1.10, 0.60, 0.50, 0.05, 0.02),
        ]

    def apply_scenario(self, frame: pd.DataFrame, scenario: StressScenario) -> pd.DataFrame:
        work = frame.copy()
        if len(work) == 0:
            return work

        profit = pd.to_numeric(work.get("profit", 0.0), errors="coerce").fillna(0.0).astype(float)
        stake = pd.to_numeric(work.get("stake", 1.0), errors="coerce").fillna(1.0).astype(float)

        gains = profit > 0
        work["stress_profit"] = np.where(
            gains,
            profit * scenario.profit_scale * (1.0 - scenario.uncertainty_penalty - scenario.calibration_penalty),
            profit * scenario.loss_scale * (1.0 + scenario.uncertainty_penalty + scenario.calibration_penalty),
        )
        work["stress_stake"] = stake * scenario.stake_scale * scenario.exposure_scale
        if "bankroll" in work.columns:
            start_bankroll = float(pd.to_numeric(work["bankroll"], errors="coerce").fillna(0.0).astype(float).iloc[0])
        else:
            start_bankroll = float(max(1.0, np.sum(np.abs(work["stress_profit"].head(1).values))))
        work["stress_bankroll"] = start_bankroll + work["stress_profit"].cumsum()
        return work

    def evaluate(self, frame: pd.DataFrame, *, scenarios: Sequence[StressScenario] | None = None) -> Dict[str, pd.DataFrame]:
        work = frame.copy()
        scenarios = list(scenarios) if scenarios is not None else self.default_scenarios()
        rows = []
        curves = []
        collapse_heatmap_rows = []

        exposure_series = pd.to_numeric(work.get("stake", 1.0), errors="coerce").fillna(1.0).astype(float)
        exposure_bins = pd.qcut(exposure_series.rank(method="first"), q=min(4, max(1, len(exposure_series))), duplicates="drop") if len(exposure_series) else pd.Series(dtype=str)
        work["exposure_bin"] = exposure_bins.astype(str) if len(exposure_bins) else "all"

        for scenario in scenarios:
            stressed = self.apply_scenario(work, scenario)
            summary = self.survival.summarize(
                stressed,
                bankroll_col="stress_bankroll",
                profit_col="stress_profit",
                initial_bankroll=float(stressed["stress_bankroll"].iloc[0]) if len(stressed) else None,
                ruin_threshold=self.ruin_threshold,
            )
            metrics = summary["metrics"]
            ruin_estimate = self.ruin_estimator.estimate(
                stressed,
                profit_col="stress_profit",
                stake_col="stress_stake",
                initial_bankroll=float(stressed["stress_bankroll"].iloc[0]) if len(stressed) else None,
                ruin_threshold=self.ruin_threshold,
                simulations=500,
                horizon=len(stressed) if len(stressed) else None,
            )

            rows.append(
                {
                    "scenario": scenario.name,
                    "probability_of_ruin": ruin_estimate["ruin_probability"],
                    "max_recovery_duration": metrics.get("max_recovery_duration", 0),
                    "stress_drawdown": metrics.get("stress_drawdown", 0.0),
                    "bankroll_half_life": metrics.get("bankroll_half_life", -1),
                    "recovery_speed": metrics.get("recovery_speed", 0.0),
                    "volatility_adjusted_survival": metrics.get("volatility_adjusted_survival", 0.0),
                    "risk_adjusted_longevity": metrics.get("risk_adjusted_longevity", 0.0),
                    "final_bankroll": metrics.get("end_bankroll", 0.0),
                }
            )

            curve = summary["curve"].copy()
            curve["scenario"] = scenario.name
            curves.append(curve)

            collapse_heatmap_rows.append(
                {
                    "scenario": scenario.name,
                    "exposure_scale": scenario.exposure_scale,
                    "collapse_risk": ruin_estimate["ruin_probability"],
                    "stress_drawdown": metrics.get("stress_drawdown", 0.0),
                }
            )

        return {
            "stress_report": pd.DataFrame.from_records(rows),
            "survival_curves": pd.concat(curves, ignore_index=True) if curves else pd.DataFrame(),
            "collapse_heatmap": pd.DataFrame.from_records(collapse_heatmap_rows),
        }
