from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd


def _safe_roi(profit: float, stake: float) -> float:
    if stake <= 0:
        return 0.0
    return float(profit / stake)


def _max_drawdown(profit_series: pd.Series) -> tuple[float, float]:
    equity = profit_series.fillna(0.0).cumsum()
    peak = equity.cummax()
    drawdown = equity - peak
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    max_drawdown_ratio = float(abs(max_drawdown) / max(float(peak.max()), 1.0)) if len(drawdown) else 0.0
    return max_drawdown, max_drawdown_ratio


def _calibration_gap(frame: pd.DataFrame, prob_col: str, hit_col: str) -> float:
    if prob_col not in frame.columns or hit_col not in frame.columns or len(frame) == 0:
        return 0.0
    prob = pd.to_numeric(frame[prob_col], errors="coerce").fillna(0.0).astype(float)
    hit = pd.to_numeric(frame[hit_col], errors="coerce").fillna(0.0).astype(float)
    return float(abs(float(prob.mean()) - float(hit.mean())))


class RegimeSurvivalMetrics:
    """Compute explainable regime-specific ROI, drawdown, calibration, and survival metrics."""

    def __init__(self, roi_weight: float = 0.35, drawdown_weight: float = 0.35, calibration_weight: float = 0.20, uncertainty_weight: float = 0.10):
        self.roi_weight = float(roi_weight)
        self.drawdown_weight = float(drawdown_weight)
        self.calibration_weight = float(calibration_weight)
        self.uncertainty_weight = float(uncertainty_weight)

    def summarize(self, frame: pd.DataFrame, *, regime_col: str = "regime", profit_col: str = "profit", stake_col: str = "stake", drawdown_col: str = "drawdown", uncertainty_col: str = "uncertainty_mean", prob_col: str = "probability", hit_col: str = "hit", order_col: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        work = frame.copy()
        if order_col and order_col in work.columns:
            work = work.sort_values(order_col)

        if stake_col not in work.columns:
            work[stake_col] = 1.0
        if profit_col not in work.columns:
            work[profit_col] = 0.0
        if uncertainty_col not in work.columns:
            work[uncertainty_col] = 0.0

        roi_rows = []
        drawdown_rows = []
        calibration_rows = []
        uncertainty_rows = []
        survival_rows = []

        for regime, grp in work.groupby(regime_col, dropna=False):
            regime_name = str(regime)
            profit = pd.to_numeric(grp[profit_col], errors="coerce").fillna(0.0).astype(float)
            stake = pd.to_numeric(grp[stake_col], errors="coerce").fillna(0.0).astype(float)
            unc = pd.to_numeric(grp[uncertainty_col], errors="coerce").fillna(0.0).astype(float)

            total_profit = float(profit.sum())
            total_stake = float(stake.sum())
            roi = _safe_roi(total_profit, total_stake)
            max_dd, max_dd_ratio = _max_drawdown(profit)
            avg_dd = float((profit.cumsum() - profit.cumsum().cummax()).mean()) if len(profit) else 0.0
            calib_gap = _calibration_gap(grp, prob_col, hit_col)
            brier = float(np.mean((pd.to_numeric(grp[prob_col], errors="coerce").fillna(0.0).astype(float) - pd.to_numeric(grp[hit_col], errors="coerce").fillna(0.0).astype(float)) ** 2)) if prob_col in grp.columns and hit_col in grp.columns and len(grp) else 0.0
            uncertainty_mean = float(unc.mean()) if len(unc) else 0.0
            uncertainty_std = float(unc.std()) if len(unc) else 0.0
            ruin_probability = float(np.mean((profit.cumsum() <= 0.0).astype(float))) if len(profit) else 0.0

            roi_rows.append({
                regime_col: regime_name,
                "n_events": int(len(grp)),
                "total_profit": total_profit,
                "total_stake": total_stake,
                "roi": roi,
            })

            drawdown_rows.append({
                regime_col: regime_name,
                "n_events": int(len(grp)),
                "max_drawdown": max_dd,
                "max_drawdown_ratio": max_dd_ratio,
                "avg_drawdown": avg_dd,
            })

            calibration_rows.append({
                regime_col: regime_name,
                "n_events": int(len(grp)),
                "calibration_gap": calib_gap,
                "brier_score": brier,
            })

            uncertainty_rows.append({
                regime_col: regime_name,
                "n_events": int(len(grp)),
                "mean_uncertainty": uncertainty_mean,
                "std_uncertainty": uncertainty_std,
            })

            roi_health = float(np.clip((roi + 0.5) / 1.0, 0.0, 1.0))
            drawdown_health = float(np.clip(1.0 - max_dd_ratio, 0.0, 1.0))
            calibration_health = float(np.clip(1.0 - (calib_gap * 2.0), 0.0, 1.0))
            uncertainty_health = float(np.clip(1.0 - uncertainty_mean, 0.0, 1.0))
            survival_score = 100.0 * (
                self.roi_weight * roi_health
                + self.drawdown_weight * drawdown_health
                + self.calibration_weight * calibration_health
                + self.uncertainty_weight * uncertainty_health
            )

            survival_rows.append({
                regime_col: regime_name,
                "n_events": int(len(grp)),
                "roi_health": roi_health,
                "drawdown_health": drawdown_health,
                "calibration_health": calibration_health,
                "uncertainty_health": uncertainty_health,
                "survival_score": survival_score,
                "ruin_probability": ruin_probability,
            })

        return {
            "roi_table": pd.DataFrame.from_records(roi_rows).sort_values("roi", ascending=False) if roi_rows else pd.DataFrame(),
            "drawdown_table": pd.DataFrame.from_records(drawdown_rows).sort_values("max_drawdown_ratio", ascending=False) if drawdown_rows else pd.DataFrame(),
            "calibration_table": pd.DataFrame.from_records(calibration_rows).sort_values("calibration_gap", ascending=False) if calibration_rows else pd.DataFrame(),
            "uncertainty_table": pd.DataFrame.from_records(uncertainty_rows).sort_values("mean_uncertainty", ascending=False) if uncertainty_rows else pd.DataFrame(),
            "survival_table": pd.DataFrame.from_records(survival_rows).sort_values("survival_score", ascending=False) if survival_rows else pd.DataFrame(),
        }
