# learning/performance_analyzer.py

import os

import pandas as pd
import numpy as np

from core.betting.uncertainty_monitor import analyze_uncertainty_history


class PerformanceAnalyzer:
    """
    Survival Performance Analyzer

    目的:
    - ROIではなく survival を監視
    - drawdown
    - volatility
    - calibration quality
    - bankroll stability

    を分析する
    """

    _cache = {}

    def analyze(
        self,
        path="derived/bets.csv",
    ):

        mtime = os.path.getmtime(path)
        cache_key = (os.path.abspath(path), mtime)
        if cache_key in self._cache:
            return self._cache[cache_key]

        df = pd.read_csv(path)

        if len(df) == 0:
            return {}

        # -----------------------------------------
        # clean
        # -----------------------------------------

        df["profit"] = pd.to_numeric(
            df["profit"],
            errors="coerce",
        ).fillna(0)

        df["stake"] = pd.to_numeric(
            df["stake"],
            errors="coerce",
        ).fillna(0)

        df["probability"] = pd.to_numeric(
            df["probability"],
            errors="coerce",
        )

        df["hit"] = pd.to_numeric(
            df["hit"],
            errors="coerce",
        )

        df["bankroll"] = pd.to_numeric(
            df["bankroll"],
            errors="coerce",
        )

        if "odds" in df.columns:
            df["odds"] = pd.to_numeric(
                df["odds"],
                errors="coerce",
            )

        if "edge" in df.columns:
            df["edge"] = pd.to_numeric(
                df["edge"],
                errors="coerce",
            )

        if "expected_value" in df.columns:
            df["expected_value"] = pd.to_numeric(
                df["expected_value"],
                errors="coerce",
            )

        if "regime" not in df.columns:
            df["regime"] = "UNKNOWN"

        # -----------------------------------------
        # ROI
        # -----------------------------------------

        total_stake = df["stake"].sum()

        if total_stake > 0:
            roi = (
                df["profit"].sum()
                / total_stake
            )
        else:
            roi = 0

        # -----------------------------------------
        # Hit Rate
        # -----------------------------------------

        hit_rate = df["hit"].mean()

        # -----------------------------------------
        # Brier Score
        # -----------------------------------------

        valid = df.dropna(
            subset=["probability", "hit"]
        )

        if len(valid) > 0:

            brier = np.mean(
                (
                    valid["probability"]
                    - valid["hit"]
                ) ** 2
            )

        else:
            brier = None

        ece = self._expected_calibration_error(valid)

        # -----------------------------------------
        # Bankroll Curve
        # -----------------------------------------

        bankroll_curve = (
            df["profit"].cumsum()
        )

        peak = bankroll_curve.cummax()

        drawdown = bankroll_curve - peak

        max_drawdown = drawdown.min()

        # -----------------------------------------
        # Volatility
        # -----------------------------------------

        profit_std = df["profit"].std()

        # -----------------------------------------
        # Sharpe-like
        # -----------------------------------------

        if profit_std and profit_std > 0:

            sharpe = (
                df["profit"].mean()
                / profit_std
            )

        else:
            sharpe = 0

        # -----------------------------------------
        # Exposure Risk
        # -----------------------------------------

        avg_stake_ratio = np.mean(
            df["stake"]
            / df["bankroll"].replace(0, np.nan)
        )

        # -----------------------------------------
        # Losing Streak
        # -----------------------------------------

        losses = (df["profit"] < 0).astype(int)

        max_lose_streak = 0
        current = 0

        for l in losses:

            if l:
                current += 1
                max_lose_streak = max(
                    max_lose_streak,
                    current,
                )
            else:
                current = 0

        # -----------------------------------------
        # Survival Score
        # -----------------------------------------

        survival_score = 1.0

        # DD penalty
        if max_drawdown < -0.3:
            survival_score *= 0.6

        elif max_drawdown < -0.15:
            survival_score *= 0.8

        # volatility penalty
        if profit_std > 5000:
            survival_score *= 0.8

        # calibration penalty
        if brier and brier > 0.2:
            survival_score *= 0.7

        # overbet penalty
        if avg_stake_ratio > 0.08:
            survival_score *= 0.8

        # -----------------------------------------
        # Final Report
        # -----------------------------------------

        odds_roi = self._segmented_roi(df, "odds", bins=[1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 100.0])
        confidence_roi = self._segmented_roi(df, "probability", bins=[0.0, 0.1, 0.2, 0.35, 0.5, 0.7, 1.0])
        regime_roi = self._regime_roi(df)
        edge_quality = self._edge_quality(df)
        uncertainty_analysis = analyze_uncertainty_history(df)
        readiness = self._phase1_readiness(df)

        result = {
            "roi": round(roi, 4),
            "hit_rate": round(hit_rate, 4),
            "brier": (
                round(brier, 4)
                if brier is not None
                else None
            ),
            "ece": (
                round(ece, 4)
                if ece is not None
                else None
            ),
            "max_drawdown": round(
                max_drawdown,
                2,
            ),
            "volatility": round(
                profit_std,
                2,
            ),
            "sharpe": round(
                sharpe,
                4,
            ),
            "avg_stake_ratio": round(
                avg_stake_ratio,
                4,
            ),
            "max_lose_streak": (
                max_lose_streak
            ),
            "survival_score": round(
                survival_score,
                4,
            ),
            "total_bets": len(df),
            "roi_by_odds_bin": odds_roi,
            "roi_by_confidence_bin": confidence_roi,
            "roi_by_regime": regime_roi,
            "edge_quality": edge_quality,
            "uncertainty_analysis": uncertainty_analysis,
            "phase1_readiness": readiness,
        }
        self._cache = {
            key: value
            for key, value in self._cache.items()
            if key[0] != cache_key[0]
        }
        self._cache[cache_key] = result
        return result

    def _expected_calibration_error(self, valid, bins=10):
        if valid is None or valid.empty:
            return None

        work = valid[["probability", "hit"]].dropna().copy()
        if work.empty:
            return None

        work["probability"] = pd.to_numeric(work["probability"], errors="coerce")
        work["hit"] = pd.to_numeric(work["hit"], errors="coerce")
        work = work.dropna(subset=["probability", "hit"])
        if work.empty:
            return None

        edges = np.linspace(0.0, 1.0, bins + 1)
        total = len(work)
        ece = 0.0
        for start, end in zip(edges[:-1], edges[1:]):
            if end == 1.0:
                bucket = work[(work["probability"] >= start) & (work["probability"] <= end)]
            else:
                bucket = work[(work["probability"] >= start) & (work["probability"] < end)]
            if bucket.empty:
                continue
            ece += (len(bucket) / total) * abs(
                float(bucket["probability"].mean()) - float(bucket["hit"].mean())
            )
        return float(ece)

    def _phase1_readiness(self, df):
        if "mode" in df.columns:
            shadow = df[df["mode"].astype(str).str.upper() == "SHADOW_MODE"].copy()
        else:
            shadow = df.copy()

        if "hit" in shadow.columns:
            shadow["hit"] = pd.to_numeric(shadow["hit"], errors="coerce")
            settled = shadow.dropna(subset=["hit"])
        else:
            settled = shadow.iloc[0:0]

        valid = settled.dropna(subset=["probability", "hit"]) if "probability" in settled.columns else settled.iloc[0:0]
        if valid.empty:
            brier = None
            ece = None
        else:
            probs = pd.to_numeric(valid["probability"], errors="coerce")
            hits = pd.to_numeric(valid["hit"], errors="coerce")
            metric_frame = pd.DataFrame({"probability": probs, "hit": hits}).dropna()
            if metric_frame.empty:
                brier = None
                ece = None
            else:
                brier = float(np.mean((metric_frame["probability"] - metric_frame["hit"]) ** 2))
                ece = self._expected_calibration_error(metric_frame)

        ev_column = None
        for candidate in ("expected_value_per_unit", "expected_value"):
            if candidate in settled.columns:
                ev_column = candidate
                break

        mean_ev = None
        if ev_column is not None and not settled.empty:
            mean_ev = float(pd.to_numeric(settled[ev_column], errors="coerce").mean())

        checks = {
            "shadow_bets_300": int(len(settled)) >= 300,
            "ev_positive": mean_ev is not None and mean_ev > 0.0,
            "brier_below_0_22": brier is not None and float(brier) < 0.22,
            "ece_below_0_05": ece is not None and float(ece) < 0.05,
        }

        return {
            "phase": "PHASE_1_SHADOW",
            "ready": all(checks.values()),
            "shadow_bets": int(len(settled)),
            "mean_ev": round(mean_ev, 6) if mean_ev is not None else None,
            "brier": round(float(brier), 6) if brier is not None else None,
            "ece": round(float(ece), 6) if ece is not None else None,
            "checks": checks,
        }

    def _segmented_roi(self, df, col, bins):

        if col not in df.columns:
            return []

        work = df.copy()
        work = work.dropna(subset=[col])
        if len(work) == 0:
            return []

        work["segment"] = pd.cut(
            work[col],
            bins=bins,
            include_lowest=True,
        )

        rows = []
        for key, grp in work.groupby("segment", observed=False):
            stake = float(grp["stake"].sum())
            profit = float(grp["profit"].sum())
            roi = (profit / stake) if stake > 0 else 0.0
            rows.append({
                "segment": str(key),
                "bets": int(len(grp)),
                "stake": round(stake, 2),
                "profit": round(profit, 2),
                "roi": round(float(roi), 4),
            })

        return rows

    def _regime_roi(self, df):

        if "regime" not in df.columns:
            return []

        rows = []
        for regime, grp in df.groupby("regime", observed=False):
            stake = float(grp["stake"].sum())
            profit = float(grp["profit"].sum())
            roi = (profit / stake) if stake > 0 else 0.0
            rows.append({
                "regime": str(regime),
                "bets": int(len(grp)),
                "roi": round(float(roi), 4),
            })

        rows.sort(key=lambda x: x["roi"], reverse=True)
        return rows

    def _edge_quality(self, df):

        if "edge" not in df.columns:
            return {}

        work = df.dropna(subset=["edge"])
        if len(work) == 0:
            return {}

        weak = work[work["edge"] < 0.02]
        medium = work[(work["edge"] >= 0.02) & (work["edge"] < 0.05)]
        strong = work[work["edge"] >= 0.05]

        def segment_stats(frame):
            if len(frame) == 0:
                return {"bets": 0, "roi": 0.0}
            stake = float(frame["stake"].sum())
            profit = float(frame["profit"].sum())
            roi = (profit / stake) if stake > 0 else 0.0
            return {
                "bets": int(len(frame)),
                "roi": round(float(roi), 4),
            }

        return {
            "weak": segment_stats(weak),
            "medium": segment_stats(medium),
            "strong": segment_stats(strong),
        }

    def __init__(self):
        self._profits = []

    def record(self, profit):
        self._profits.append(float(profit))

    def summary(self):
        if not self._profits:
            return {
                "mean_profit": 0.0,
                "volatility": 0.0,
                "max_drawdown": 0.0,
            }

        profits = np.array(self._profits, dtype=float)
        equity = np.cumsum(profits)
        peak = np.maximum.accumulate(equity)
        drawdown = equity - peak

        return {
            "mean_profit": float(np.mean(profits)),
            "volatility": float(np.std(profits)),
            "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        }
