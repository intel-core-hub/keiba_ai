from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence

import numpy as np
try:
    import pandas as pd
except Exception:
    pd = None


@dataclass
class RuinEstimate:
    ruin_probability: float
    survival_probability: float
    median_final_bankroll: float
    mean_final_bankroll: float
    worst_final_bankroll: float
    best_final_bankroll: float
    percentile_05: float
    percentile_95: float


class RuinProbabilityEstimator:
    """Bootstrap-based ruin estimator with explicit bankroll dynamics."""

    def estimate(
        self,
        frame: pd.DataFrame,
        *,
        profit_col: str = "profit",
        stake_col: str = "stake",
        initial_bankroll: float | None = None,
        ruin_threshold: float = 0.3,
        simulations: int = 2000,
        horizon: int | None = None,
        random_state: int = 42,
    ) -> Dict[str, float]:
        if frame is None or len(frame) == 0:
            return {
                "ruin_probability": 0.0,
                "survival_probability": 1.0,
                "median_final_bankroll": 0.0,
                "mean_final_bankroll": 0.0,
                "worst_final_bankroll": 0.0,
                "best_final_bankroll": 0.0,
                "percentile_05": 0.0,
                "percentile_95": 0.0,
            }

        work = frame.copy()
        profit = pd.to_numeric(work.get(profit_col, 0.0), errors="coerce").fillna(0.0).astype(float).values
        stake = pd.to_numeric(work.get(stake_col, 1.0), errors="coerce").fillna(1.0).astype(float).values
        stake = np.where(stake <= 0, 1.0, stake)

        if initial_bankroll is None:
            bankroll_source = work["bankroll"] if "bankroll" in work.columns else pd.Series([max(1.0, float(np.sum(np.abs(profit))))])
            initial_bankroll = float(pd.to_numeric(bankroll_source, errors="coerce").fillna(0.0).iloc[0])
            if initial_bankroll <= 0:
                initial_bankroll = float(max(1.0, np.sum(stake)))

        if horizon is None:
            horizon = len(work)

        rng = np.random.default_rng(random_state)
        finals = []
        ruins = 0

        for _ in range(int(simulations)):
            bankroll = float(initial_bankroll)
            sample_idx = rng.integers(0, len(profit), size=int(horizon))
            for idx in sample_idx:
                bankroll += float(profit[idx])
                if bankroll <= initial_bankroll * ruin_threshold:
                    ruins += 1
                    finals.append(bankroll)
                    break
            else:
                finals.append(bankroll)

        finals_arr = np.asarray(finals, dtype=float)
        ruin_probability = float(ruins / max(simulations, 1))
        return {
            "ruin_probability": ruin_probability,
            "survival_probability": float(1.0 - ruin_probability),
            "median_final_bankroll": float(np.median(finals_arr)),
            "mean_final_bankroll": float(np.mean(finals_arr)),
            "worst_final_bankroll": float(np.min(finals_arr)),
            "best_final_bankroll": float(np.max(finals_arr)),
            "percentile_05": float(np.percentile(finals_arr, 5)),
            "percentile_95": float(np.percentile(finals_arr, 95)),
        }
