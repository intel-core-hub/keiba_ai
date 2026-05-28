from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
try:
    import pandas as pd
except Exception:
    pd = None

from core.stress_test_engine import StressTestEngine
from core.survival_metrics import SurvivalMetricsSystem


class ResilienceAnalyzer:
    """Combine longevity, collapse risk, recovery, and sensitivity analysis."""

    def __init__(self, ruin_threshold: float = 0.3):
        self.survival = SurvivalMetricsSystem()
        self.stress = StressTestEngine(ruin_threshold=ruin_threshold)

    def _group_table(self, frame: pd.DataFrame, group_col: str, label: str) -> pd.DataFrame:
        if group_col not in frame.columns or len(frame) == 0:
            return pd.DataFrame(columns=[label])

        rows = []
        for key, grp in frame.groupby(group_col, dropna=False, observed=False):
            summary = self.survival.summarize(grp, bankroll_col="bankroll", profit_col="profit", initial_bankroll=float(grp["bankroll"].iloc[0]) if "bankroll" in grp.columns else None)
            metrics = summary["metrics"]
            rows.append(
                {
                    label: str(key),
                    "n_events": int(len(grp)),
                    "probability_of_ruin": metrics.get("probability_of_ruin", 0.0),
                    "max_recovery_duration": metrics.get("max_recovery_duration", 0),
                    "stress_drawdown": metrics.get("stress_drawdown", 0.0),
                    "recovery_speed": metrics.get("recovery_speed", 0.0),
                    "volatility_adjusted_survival": metrics.get("volatility_adjusted_survival", 0.0),
                    "risk_adjusted_longevity": metrics.get("risk_adjusted_longevity", 0.0),
                }
            )
        return pd.DataFrame.from_records(rows).sort_values(["probability_of_ruin", "stress_drawdown"], ascending=False)

    def analyze(self, frame: pd.DataFrame) -> Dict[str, pd.DataFrame | Dict[str, float]]:
        if frame is None or len(frame) == 0:
            return {
                "baseline_curve": pd.DataFrame(),
                "recovery_analysis": pd.DataFrame(),
                "stress_report": pd.DataFrame(),
                "collapse_heatmap": pd.DataFrame(),
                "aggressive_vs_defensive": pd.DataFrame(),
                "uncertainty_aware_survival": pd.DataFrame(),
                "regime_aware_survival": pd.DataFrame(),
                "calibration_deterioration_survival": pd.DataFrame(),
                "exposure_sensitivity": pd.DataFrame(),
                "summary": {},
            }

        work = frame.copy()
        if "profit" not in work.columns and "pnl" in work.columns:
            work["profit"] = work["pnl"]
        if "stake" not in work.columns:
            work["stake"] = 1.0
        if "bankroll" not in work.columns:
            work["bankroll"] = work["profit"].cumsum() + float(max(1.0, work["stake"].iloc[0]))

        baseline = self.survival.summarize(work, bankroll_col="bankroll", profit_col="profit", initial_bankroll=float(work["bankroll"].iloc[0]))
        stress = self.stress.evaluate(work)

        exposure_source = pd.to_numeric(work.get("risk_multiplier", work.get("stake", 1.0)), errors="coerce").fillna(1.0).astype(float)
        work["exposure_bucket"] = pd.qcut(exposure_source.rank(method="first"), q=min(4, max(1, len(exposure_source))), duplicates="drop") if len(exposure_source) else "all"

        uncertainty_source = "uncertainty_mean" if "uncertainty_mean" in work.columns else ("uncertainty_score" if "uncertainty_score" in work.columns else None)
        if uncertainty_source:
            work["uncertainty_bucket"] = pd.qcut(pd.to_numeric(work[uncertainty_source], errors="coerce").fillna(0.0).rank(method="first"), q=min(4, max(1, len(work))), duplicates="drop")
        else:
            work["uncertainty_bucket"] = "unknown"

        calibration_source = "calibration_gap" if "calibration_gap" in work.columns else None
        if calibration_source:
            work["calibration_bucket"] = pd.qcut(pd.to_numeric(work[calibration_source], errors="coerce").fillna(0.0).rank(method="first"), q=min(4, max(1, len(work))), duplicates="drop")
        else:
            work["calibration_bucket"] = "unknown"

        aggressive_vs_defensive = self._group_table(work, "exposure_bucket", "exposure_bucket")
        uncertainty_aware = self._group_table(work, "uncertainty_bucket", "uncertainty_bucket")
        regime_aware = self._group_table(work, "regime", "regime") if "regime" in work.columns else pd.DataFrame()
        calibration_survival = self._group_table(work, "calibration_bucket", "calibration_bucket")
        exposure_sensitivity = aggressive_vs_defensive.rename(columns={"exposure_bucket": "exposure_bucket"}) if len(aggressive_vs_defensive) else pd.DataFrame()

        summary_metrics = baseline["metrics"].copy()
        stress_report = stress["stress_report"].copy()
        collapse_heatmap = stress["collapse_heatmap"].copy()
        summary_metrics["exposure_collapse_risk"] = float(collapse_heatmap["collapse_risk"].max()) if len(collapse_heatmap) else 0.0

        if len(stress_report):
            resilience_score = float(
                100.0
                * np.clip(
                    0.25 * (1.0 - float(stress_report["probability_of_ruin"].mean()))
                    + 0.20 * float(np.clip(1.0 - stress_report["stress_drawdown"].mean(), 0.0, 1.0))
                    + 0.20 * float(np.clip(1.0 - summary_metrics.get("max_drawdown", 0.0), 0.0, 1.0))
                    + 0.20 * float(np.clip(summary_metrics.get("recovery_speed", 0.0), 0.0, 1.0))
                    + 0.15 * float(np.clip(summary_metrics.get("volatility_adjusted_survival", 0.0), 0.0, 1.0)),
                    0.0,
                    1.0,
                )
            )
        else:
            resilience_score = 0.0

        summary_metrics["resilience_score"] = resilience_score

        return {
            "baseline_curve": baseline["curve"],
            "recovery_analysis": baseline["recovery_table"],
            "stress_report": stress_report,
            "collapse_heatmap": collapse_heatmap,
            "aggressive_vs_defensive": aggressive_vs_defensive,
            "uncertainty_aware_survival": uncertainty_aware,
            "regime_aware_survival": regime_aware,
            "calibration_deterioration_survival": calibration_survival,
            "exposure_sensitivity": exposure_sensitivity,
            "summary": summary_metrics,
        }
