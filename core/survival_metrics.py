from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd


@dataclass
class SurvivalCurvePoint:
    step: int
    bankroll: float
    peak: float
    drawdown: float
    underwater: bool


def _to_numeric_series(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([default] * len(frame), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype(float)


def build_bankroll_curve(
    frame: pd.DataFrame,
    *,
    bankroll_col: str = "bankroll",
    profit_col: str = "profit",
    initial_bankroll: float | None = None,
) -> pd.DataFrame:
    """Build a deterministic bankroll / peak / drawdown curve.

    If a bankroll column exists, it is used directly. Otherwise bankroll is
    reconstructed from cumulative profit and an optional initial bankroll.
    """

    work = frame.copy()
    if len(work) == 0:
        return pd.DataFrame(columns=["step", "bankroll", "peak", "drawdown", "underwater"])

    if bankroll_col in work.columns:
        bankroll = _to_numeric_series(work, bankroll_col)
    else:
        profit = _to_numeric_series(work, profit_col)
        start = float(initial_bankroll if initial_bankroll is not None else max(1.0, abs(profit.iloc[0]) if len(profit) else 1.0))
        bankroll = start + profit.cumsum()

    peak = bankroll.cummax()
    drawdown = bankroll - peak

    curve = pd.DataFrame(
        {
            "step": np.arange(len(work), dtype=int),
            "bankroll": bankroll.values,
            "peak": peak.values,
            "drawdown": drawdown.values,
            "underwater": (drawdown.values < 0).astype(bool),
        }
    )
    return curve


def compute_recovery_durations(curve: pd.DataFrame) -> pd.DataFrame:
    """Return recovery episodes with duration and recovery speed.

    A recovery episode starts when bankroll falls below the previous peak and
    ends when it reclaims that peak.
    """

    if len(curve) == 0:
        return pd.DataFrame(columns=["start_step", "end_step", "duration", "recovery_speed", "max_drawdown"])

    records = []
    peak = float(curve.iloc[0]["bankroll"])
    underwater_start: Optional[int] = None
    underwater_peak = peak

    for row in curve.itertuples(index=False):
        step = int(row.step)
        bankroll = float(row.bankroll)
        if bankroll >= peak:
            if underwater_start is not None:
                duration = step - underwater_start
                max_drawdown = float(abs(curve.loc[underwater_start:step, "drawdown"].min()))
                records.append(
                    {
                        "start_step": underwater_start,
                        "end_step": step,
                        "duration": duration,
                        "recovery_speed": float(1.0 / max(duration, 1)),
                        "max_drawdown": max_drawdown,
                    }
                )
                underwater_start = None
            peak = bankroll
            underwater_peak = peak
        elif bankroll < peak and underwater_start is None:
            underwater_start = step
            underwater_peak = peak

    if underwater_start is not None:
        end_step = int(curve.iloc[-1]["step"])
        duration = end_step - underwater_start + 1
        max_drawdown = float(abs(curve.loc[underwater_start:, "drawdown"].min()))
        records.append(
            {
                "start_step": underwater_start,
                "end_step": end_step,
                "duration": duration,
                "recovery_speed": float(1.0 / max(duration, 1)),
                "max_drawdown": max_drawdown,
            }
        )

    return pd.DataFrame.from_records(records)


class SurvivalMetricsSystem:
    """Explainable survivability metrics focused on longevity and collapse risk."""

    def summarize(
        self,
        frame: pd.DataFrame,
        *,
        bankroll_col: str = "bankroll",
        profit_col: str = "profit",
        initial_bankroll: float | None = None,
        ruin_threshold: float = 0.3,
    ) -> Dict[str, object]:
        curve = build_bankroll_curve(
            frame,
            bankroll_col=bankroll_col,
            profit_col=profit_col,
            initial_bankroll=initial_bankroll,
        )

        if len(curve) == 0:
            return {
                "curve": curve,
                "recovery_table": pd.DataFrame(),
                "metrics": {},
            }

        start_bankroll = float(curve.iloc[0]["bankroll"])
        end_bankroll = float(curve.iloc[-1]["bankroll"])
        peak_bankroll = float(curve["peak"].max())
        min_bankroll = float(curve["bankroll"].min())
        drawdown_abs = curve["drawdown"].astype(float)
        drawdown_ratio = np.where(curve["peak"] > 0, np.abs(drawdown_abs) / curve["peak"], 0.0)
        max_drawdown = float(np.max(drawdown_ratio)) if len(drawdown_ratio) else 0.0
        max_stress_drawdown = float(np.min(drawdown_abs)) if len(drawdown_abs) else 0.0

        returns = curve["bankroll"].diff().fillna(0.0)
        volatility = float(returns.std()) if len(returns) > 1 else 0.0
        volatility_adjusted_survival = float((end_bankroll / max(start_bankroll, 1.0)) / (1.0 + volatility / max(start_bankroll, 1.0)))

        recovery_table = compute_recovery_durations(curve)
        max_recovery_duration = int(recovery_table["duration"].max()) if len(recovery_table) else 0
        avg_recovery_duration = float(recovery_table["duration"].mean()) if len(recovery_table) else 0.0
        recovery_speed = float(1.0 / avg_recovery_duration) if avg_recovery_duration > 0 else 0.0

        half_bankroll = start_bankroll * 0.5
        half_life_rows = curve.index[curve["bankroll"] <= half_bankroll].tolist()
        bankroll_half_life = int(half_life_rows[0]) if half_life_rows else -1

        ruin_probability = float(np.mean(curve["bankroll"] <= start_bankroll * ruin_threshold))
        risk_adjusted_longevity = float(
            max(0.0, (len(curve) - max_recovery_duration) / max(len(curve), 1))
            * max(0.0, 1.0 - max_drawdown)
            * max(0.0, volatility_adjusted_survival)
        )

        survival_curve = curve.assign(
            return_step=returns.values,
            drawdown_ratio=drawdown_ratio,
            survival_indicator=(curve["bankroll"] > start_bankroll * ruin_threshold).astype(int),
        )

        metrics = {
            "start_bankroll": start_bankroll,
            "end_bankroll": end_bankroll,
            "peak_bankroll": peak_bankroll,
            "min_bankroll": min_bankroll,
            "probability_of_ruin": ruin_probability,
            "max_recovery_duration": max_recovery_duration,
            "avg_recovery_duration": avg_recovery_duration,
            "recovery_speed": recovery_speed,
            "bankroll_half_life": bankroll_half_life,
            "stress_drawdown": float(abs(max_stress_drawdown)),
            "volatility_adjusted_survival": volatility_adjusted_survival,
            "risk_adjusted_longevity": risk_adjusted_longevity,
            "max_drawdown": max_drawdown,
            "final_growth": float((end_bankroll / max(start_bankroll, 1.0)) - 1.0),
        }

        return {
            "curve": survival_curve,
            "recovery_table": recovery_table,
            "metrics": metrics,
        }
