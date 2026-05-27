from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


@dataclass
class UncertaintyMonitorConfig:
    rolling_window: int = 100
    short_window: int = 20
    deterioration_delta: float = 0.04
    deterioration_ratio: float = 1.10
    drift_threshold: float = 0.05
    min_samples: int = 20


class UncertaintyMonitor:
    def __init__(self, cfg: Optional[UncertaintyMonitorConfig] = None):
        self.cfg = cfg or UncertaintyMonitorConfig()
        self.uncertainty: Deque[float] = deque(maxlen=self.cfg.rolling_window)
        self.drift: Deque[float] = deque(maxlen=self.cfg.rolling_window)
        self.calibration_gap: Deque[float] = deque(maxlen=self.cfg.rolling_window)
        self.drawdown: Deque[float] = deque(maxlen=self.cfg.rolling_window)
        self.roi: Deque[float] = deque(maxlen=self.cfg.rolling_window)
        self.false_edge: Deque[int] = deque(maxlen=self.cfg.rolling_window)

    def record(
        self,
        uncertainty_score: float,
        drift_score: float | None = None,
        calibration_gap: float | None = None,
        drawdown: float | None = None,
        roi: float | None = None,
        edge: float | None = None,
        profit: float | None = None,
    ):
        self.uncertainty.append(float(uncertainty_score))

        if drift_score is not None:
            self.drift.append(float(drift_score))

        if calibration_gap is not None:
            self.calibration_gap.append(float(calibration_gap))

        if drawdown is not None:
            self.drawdown.append(float(drawdown))

        if roi is not None:
            self.roi.append(float(roi))

        if edge is not None and profit is not None:
            self.false_edge.append(int(float(edge) > 0.0 and float(profit) <= 0.0))

    def rolling_mean(self) -> float:
        return float(np.mean(self.uncertainty)) if self.uncertainty else 0.0

    def previous_mean(self) -> float:
        if len(self.uncertainty) < self.cfg.short_window * 2:
            return 0.0
        arr = np.asarray(self.uncertainty, dtype=float)
        prev = arr[-self.cfg.short_window * 2:-self.cfg.short_window]
        return float(np.mean(prev)) if len(prev) else 0.0

    def deteriorating(self) -> bool:
        if len(self.uncertainty) < self.cfg.min_samples:
            return False

        recent = self._window_mean(self.cfg.short_window)
        prior = self.previous_mean()

        if prior <= 0:
            return recent > self.cfg.deterioration_delta

        return (recent - prior) >= self.cfg.deterioration_delta and recent >= prior * self.cfg.deterioration_ratio

    def drift_worsening(self) -> bool:
        if len(self.drift) < self.cfg.min_samples:
            return False
        recent = self._window_mean(self.cfg.short_window, source=self.drift)
        previous = self._window_mean(self.cfg.short_window, source=self._previous_deque(self.drift))
        return recent >= max(self.cfg.drift_threshold, previous + self.cfg.deterioration_delta)

    def summary(self) -> Dict[str, float | bool]:
        return {
            "rolling_uncertainty": round(self.rolling_mean(), 6),
            "previous_uncertainty": round(self.previous_mean(), 6),
            "deteriorating": self.deteriorating(),
            "drift_worsening": self.drift_worsening(),
            "avg_calibration_gap": round(float(np.mean(self.calibration_gap)) if self.calibration_gap else 0.0, 6),
            "avg_drawdown": round(float(np.mean(self.drawdown)) if self.drawdown else 0.0, 6),
            "avg_roi": round(float(np.mean(self.roi)) if self.roi else 0.0, 6),
            "false_edge_rate": round(float(np.mean(self.false_edge)) if self.false_edge else 0.0, 6),
        }

    def _window_mean(self, size: int, source: Optional[Iterable[float]] = None) -> float:
        data = list(source if source is not None else self.uncertainty)
        if not data:
            return 0.0
        window = data[-size:] if len(data) >= size else data
        return float(np.mean(window)) if window else 0.0

    def _previous_deque(self, source: Deque[float]) -> List[float]:
        data = list(source)
        if len(data) < self.cfg.short_window * 2:
            return data
        return data[-self.cfg.short_window * 2:-self.cfg.short_window]


def analyze_uncertainty_history(df: pd.DataFrame) -> Dict[str, object]:
    if df is None or len(df) == 0:
        return {}

    work = df.copy()

    for col in ["uncertainty_score", "probability", "hit", "profit", "stake", "edge", "drawdown", "brier_score", "ece", "reliability"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    if "uncertainty_score" not in work.columns:
        return {}

    work = work.dropna(subset=["uncertainty_score"])
    if len(work) == 0:
        return {}

    if "profit" not in work.columns:
        work["profit"] = 0.0
    if "stake" not in work.columns:
        work["stake"] = 1.0
    if "hit" not in work.columns:
        work["hit"] = np.where(work["profit"] > 0, 1, 0)

    work = work.sort_index().reset_index(drop=True)
    work["equity"] = work["profit"].fillna(0.0).cumsum()
    work["peak"] = work["equity"].cummax()
    work["drawdown_path"] = work["equity"] - work["peak"]
    if "edge" in work.columns:
        edge_series = work["edge"].fillna(0.0)
    else:
        edge_series = pd.Series(0.0, index=work.index)
    work["false_edge"] = np.where((edge_series > 0) & (work["profit"] <= 0), 1, 0)

    try:
        bins = pd.qcut(work["uncertainty_score"].rank(method="first"), q=min(5, len(work)), duplicates="drop")
    except Exception:
        bins = pd.cut(work["uncertainty_score"], bins=min(5, len(work)), include_lowest=True)
    work["uncertainty_bin"] = bins.astype(str)

    rows = []
    for label, grp in work.groupby("uncertainty_bin", observed=False):
        stake = float(grp["stake"].sum())
        profit = float(grp["profit"].sum())
        roi = (profit / stake) if stake > 0 else 0.0
        calibration_gap = None
        if "probability" in grp.columns and "hit" in grp.columns:
            calibration_gap = float(abs(float(grp["probability"].mean()) - float(grp["hit"].mean())))

        rows.append({
            "uncertainty_bin": str(label),
            "bets": int(len(grp)),
            "roi": round(float(roi), 6),
            "avg_drawdown": round(float(grp["drawdown_path"].mean()), 6),
            "avg_brier": round(float(np.mean((grp["probability"] - grp["hit"]) ** 2)) if "probability" in grp.columns else 0.0, 6),
            "calibration_gap": round(calibration_gap if calibration_gap is not None else 0.0, 6),
            "false_edge_rate": round(float(grp["false_edge"].mean()) if len(grp) else 0.0, 6),
            "avg_uncertainty": round(float(grp["uncertainty_score"].mean()), 6),
        })

    roi_corr = float(work[["uncertainty_score", "profit"]].corr(method="spearman").iloc[0, 1]) if len(work) > 1 else 0.0
    drawdown_corr = float(work[["uncertainty_score", "drawdown_path"]].corr(method="spearman").iloc[0, 1]) if len(work) > 1 else 0.0

    calibration_gap = None
    if "probability" in work.columns and "hit" in work.columns:
        calibration_gap = float(abs(float(work["probability"].mean()) - float(work["hit"].mean())))

    return {
        "overall": {
            "bets": int(len(work)),
            "mean_uncertainty": round(float(work["uncertainty_score"].mean()), 6),
            "roi_corr": round(roi_corr, 6),
            "drawdown_corr": round(drawdown_corr, 6),
            "calibration_gap": round(calibration_gap, 6) if calibration_gap is not None else None,
            "false_edge_rate": round(float(work["false_edge"].mean()), 6),
        },
        "bins": rows,
    }