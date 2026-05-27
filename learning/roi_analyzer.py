from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from learning.uncertainty import estimate_uncertainty


ODDS_BINS = [0.0, 1.5, 2.5, 4.0, 6.0, 10.0, 20.0, 50.0, math.inf]
CONFIDENCE_BINS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
EDGE_BINS = [-math.inf, -0.5, -0.2, 0.0, 0.2, 0.5, 1.0, math.inf]
UNCERTAINTY_BINS = [0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0]


@dataclass
class ROIAnalyzerConfig:
    odds_bins: Sequence[float] = tuple(ODDS_BINS)
    confidence_bins: Sequence[float] = tuple(CONFIDENCE_BINS)
    edge_bins: Sequence[float] = tuple(EDGE_BINS)
    uncertainty_bins: Sequence[float] = tuple(UNCERTAINTY_BINS)
    top_curve_steps: int = 20


class ROIAnalyzer:
    def __init__(self, config: Optional[ROIAnalyzerConfig] = None):
        self.config = config or ROIAnalyzerConfig()

    def load_csv(self, path: str | Path) -> pd.DataFrame:
        return pd.read_csv(path, low_memory=False)

    def load_jsonl(self, path: str | Path) -> pd.DataFrame:
        rows = []
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        return pd.DataFrame(rows)

    def analyze(
        self,
        source: pd.DataFrame,
        decision_log: pd.DataFrame | None = None,
        bets_log: pd.DataFrame | None = None,
    ) -> Dict[str, object]:
        work = self._prepare_source(source)
        work = self._merge_optional_source(work, decision_log, ["uncertainty_score", "calibrated_probability", "market_probability", "edge_quality", "drift_score", "brier_score", "ece", "reliability", "regime", "capital_mode", "defensive_mode", "uncertainty_multiplier", "global_exposure_multiplier", "rolling_uncertainty", "uncertainty_deteriorating", "no_bet_reason"], key_candidates=("selection_key",))
        work = self._merge_optional_source(work, bets_log, ["stake", "bankroll", "drawdown", "risk_multiplier", "lose_streak", "win_streak", "race_risk_used"], key_candidates=("selection_key",))

        if len(work) == 0:
            return {}

        work = self._derive_metrics(work)

        odds_table = self.bucket_report(work, "odds_bin")
        confidence_table = self.bucket_report(work, "confidence_bin")
        edge_table = self.edge_quality_report(work)
        uncertainty_table = self.bucket_report(work, "uncertainty_bin")
        regime_table = self.regime_profitability_report(work)
        heatmap_odds_uncertainty = self.profitability_heatmap(work, "odds_bin", "uncertainty_bin")
        heatmap_confidence_edge = self.profitability_heatmap(work, "confidence_bin", "edge_bin")
        roi_curve = self.roi_curve(work)
        drawdown_report = self.drawdown_report(work)
        survival = self.survival_metrics(work)
        calibration_roi = self.calibration_vs_roi(work)
        ev_report = self.expected_vs_realized(work)
        diagnostics = self.diagnostic_flags(work)

        overall = self.overall_summary(work, survival, calibration_roi, ev_report)

        return {
            "overall": overall,
            "data": work,
            "odds_table": odds_table,
            "confidence_table": confidence_table,
            "edge_table": edge_table,
            "uncertainty_table": uncertainty_table,
            "regime_table": regime_table,
            "heatmap_odds_uncertainty": heatmap_odds_uncertainty,
            "heatmap_confidence_edge": heatmap_confidence_edge,
            "roi_curve": roi_curve,
            "drawdown_report": drawdown_report,
            "survival": survival,
            "calibration_roi": calibration_roi,
            "expected_vs_realized": ev_report,
            "diagnostics": diagnostics,
        }

    def _prepare_source(self, df: pd.DataFrame) -> pd.DataFrame:
        work = df.copy()

        rename_map = {}
        if "horse_name" in work.columns and "selection" not in work.columns:
            rename_map["horse_name"] = "selection"
        if rename_map:
            work = work.rename(columns=rename_map)

        if "selection" not in work.columns:
            if "horse_id" in work.columns:
                work["selection"] = work["horse_id"].astype(str)
            else:
                work["selection"] = work.index.astype(str)

        work["selection_key"] = work["selection"].astype(str)
        work["race_id"] = work.get("race_id", pd.Series(range(len(work)))).astype(str)

        for column in ["odds", "pred_prob", "expected_value", "pnl", "profit", "stake", "hit", "uncertainty_score", "calibrated_probability", "market_probability", "edge_quality", "drift_score", "brier_score", "ece", "reliability", "drawdown", "risk_multiplier", "lose_streak", "win_streak", "race_risk_used", "bankroll"]:
            if column in work.columns:
                work[column] = pd.to_numeric(work[column], errors="coerce")

        if "hit" in work.columns:
            work["hit"] = work["hit"].fillna(0).astype(int)
        elif "actual_pos" in work.columns:
            work["hit"] = (pd.to_numeric(work["actual_pos"], errors="coerce") == 1).astype(int)
        else:
            work["hit"] = np.where(pd.to_numeric(work.get("pnl", 0), errors="coerce").fillna(0) > 0, 1, 0)

        if "stake" not in work.columns:
            work["stake"] = 1.0
        work["stake"] = work["stake"].fillna(1.0)

        if "profit" not in work.columns:
            if "pnl" in work.columns:
                work["profit"] = work["pnl"]
            else:
                work["profit"] = np.where(work["hit"] > 0, work.get("odds", 1.0) - 1.0, -1.0)
        work["profit"] = work["profit"].fillna(work.get("pnl", 0.0)).astype(float)

        if "expected_value" not in work.columns:
            if "pred_prob" in work.columns and "odds" in work.columns:
                work["expected_value"] = work["pred_prob"] * work["odds"]
            else:
                work["expected_value"] = 1.0
        work["expected_value"] = work["expected_value"].fillna(1.0).astype(float)

        if "pred_prob" not in work.columns:
            work["pred_prob"] = np.nan

        if "calibrated_probability" not in work.columns:
            work["calibrated_probability"] = np.nan

        if "market_probability" not in work.columns:
            work["market_probability"] = np.where(work.get("odds", pd.Series([np.nan] * len(work))).notna(), 1.0 / work["odds"].replace(0, np.nan), np.nan)

        if "regime" not in work.columns:
            work["regime"] = np.nan

        if "uncertainty_score" not in work.columns:
            work["uncertainty_score"] = np.nan

        return work.reset_index(drop=True)

    def _merge_optional_source(self, base: pd.DataFrame, extra: pd.DataFrame | None, columns: Sequence[str], key_candidates: Sequence[str]) -> pd.DataFrame:
        if extra is None or len(extra) == 0:
            return base

        work = extra.copy()
        if "horse_name" in work.columns and "selection" not in work.columns:
            work = work.rename(columns={"horse_name": "selection"})
        if "selection" not in work.columns and "horse_id" in work.columns:
            work["selection"] = work["horse_id"].astype(str)
        if "selection" not in work.columns:
            return base

        work["selection_key"] = work["selection"].astype(str)
        if "race_id" not in work.columns:
            return base

        wanted = [c for c in columns if c in work.columns]
        if not wanted:
            return base

        subset = work[["race_id", "selection_key", *wanted]].copy()
        subset = subset.drop_duplicates(subset=["race_id", "selection_key"], keep="last")

        merged = base.merge(subset, on=["race_id", "selection_key"], how="left", suffixes=("", "_extra"))
        for column in wanted:
            extra_col = f"{column}_extra"
            if extra_col in merged.columns:
                if column in merged.columns:
                    merged[column] = merged[column].combine_first(merged[extra_col])
                    merged = merged.drop(columns=[extra_col])
                else:
                    merged = merged.rename(columns={extra_col: column})

        return merged

    def _derive_metrics(self, work: pd.DataFrame) -> pd.DataFrame:
        out = work.copy()

        if out["uncertainty_score"].isna().all():
            if "calibrated_probability" in out.columns and out["calibrated_probability"].notna().any():
                out["uncertainty_score"] = out["calibrated_probability"].apply(lambda p: estimate_uncertainty(float(p), None)["uncertainty_score"] if pd.notna(p) else np.nan)
            elif out["pred_prob"].notna().any():
                out["uncertainty_score"] = out["pred_prob"].apply(lambda p: estimate_uncertainty(float(p), None)["uncertainty_score"] if pd.notna(p) else np.nan)

        out["uncertainty_score"] = out["uncertainty_score"].fillna(out["pred_prob"].apply(lambda p: estimate_uncertainty(float(p), None)["uncertainty_score"] if pd.notna(p) else 0.5))

        if out["calibrated_probability"].isna().all() and out["pred_prob"].notna().any():
            out["calibrated_probability"] = out["pred_prob"].astype(float)

        out["expected_profit"] = out["expected_value"] - 1.0
        out["realized_profit"] = out["profit"].astype(float)
        out["realized_roi_pct"] = (out["realized_profit"] / out["stake"].replace(0, np.nan)).fillna(0.0) * 100.0
        out["expected_roi_pct"] = out["expected_profit"] * 100.0
        out["calibration_gap"] = (out["pred_prob"] - out["hit"]).abs()
        out["ev_gap"] = out["expected_profit"] - (out["realized_profit"] / out["stake"].replace(0, np.nan)).fillna(0.0)
        out["market_bias"] = out["pred_prob"] - out["market_probability"].fillna(out["pred_prob"])
        out["favorite_bias"] = np.where(out["odds"] <= 2.0, 1, 0)
        out["longshot_bias"] = np.where(out["odds"] >= 10.0, 1, 0)
        out["market_regime"] = out.apply(self.infer_market_regime, axis=1)
        out["regime_label"] = out["regime"].where(out["regime"].notna(), out["market_regime"])
        out["odds_bin"] = self._safe_cut(out["odds"], self.config.odds_bins)
        out["confidence_bin"] = self._safe_cut(out["pred_prob"].fillna(out["calibrated_probability"]), self.config.confidence_bins)
        out["edge_bin"] = self._safe_cut(out["expected_profit"], self.config.edge_bins)
        out["uncertainty_bin"] = self._safe_cut(out["uncertainty_score"], self.config.uncertainty_bins)
        out["race_roi"] = out["realized_profit"] / out["stake"].replace(0, np.nan)
        out["exposure_adjusted_roi"] = out["realized_profit"] / out["stake"].replace(0, np.nan)
        out["profit_per_bet"] = out["realized_profit"]
        return out

    def _safe_cut(self, series: pd.Series, bins: Sequence[float]) -> pd.Categorical:
        clean = pd.to_numeric(series, errors="coerce")
        try:
            return pd.cut(clean, bins=bins, include_lowest=True)
        except Exception:
            # fallback to quantile-style bins when fixed binning fails on sparse data
            unique = clean.dropna().nunique()
            if unique <= 1:
                return pd.Series(["all"] * len(clean), index=clean.index, dtype="category")
            q = min(5, unique)
            try:
                return pd.qcut(clean.rank(method="first"), q=q, duplicates="drop")
            except Exception:
                return pd.Series(["all"] * len(clean), index=clean.index, dtype="category")

    def infer_market_regime(self, row: pd.Series) -> str:
        odds = row.get("odds", np.nan)
        if pd.isna(odds):
            return "UNKNOWN"
        if odds <= 2.0:
            return "FAVORITE"
        if odds <= 4.0:
            return "LOW_ODDS"
        if odds <= 8.0:
            return "BALANCED"
        if odds <= 20.0:
            return "LONGSHOT"
        return "DEEP_LONGSHOT"

    def bucket_report(self, df: pd.DataFrame, group_col: str) -> pd.DataFrame:
        rows = []
        for key, grp in df.groupby(group_col, dropna=False, observed=False):
            rows.append(self._summarize_group(grp, label=group_col, key=str(key)))
        return self._finalize_table(rows, group_col)

    def edge_quality_report(self, df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for key, grp in df.groupby("edge_bin", dropna=False, observed=False):
            summary = self._summarize_group(grp, label="edge_bin", key=str(key))
            if not summary:
                continue
            summary.update({
                "expected_positive_rate": round(float((grp["expected_profit"] > 0).mean()) * 100.0, 2),
                "realized_positive_rate": round(float((grp["realized_profit"] > 0).mean()) * 100.0, 2),
                "false_edge_rate": round(float(((grp["expected_profit"] > 0) & (grp["realized_profit"] <= 0)).mean()) * 100.0, 2),
                "edge_mae": round(float(np.mean(np.abs(grp["expected_profit"] - grp["realized_profit"]))), 6),
                "variance": round(float(grp["realized_profit"].var(ddof=0)) if len(grp) else 0.0, 6),
            })
            rows.append(summary)

        table = pd.DataFrame(rows)
        if len(table) == 0:
            return table
        cols = ["edge_bin", "count", "expected_positive_rate", "realized_positive_rate", "roi", "realized_roi_pct", "avg_expected_profit", "avg_realized_profit", "false_edge_rate", "edge_mae", "variance", "calibration_gap", "market_bias"]
        return table[cols].sort_values("edge_bin").reset_index(drop=True)

    def regime_profitability_report(self, df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for regime, grp in df.groupby("regime_label", dropna=False, observed=False):
            summary = self._summarize_group(grp, label="regime_label", key=str(regime))
            if not summary:
                continue
            summary["regime_label"] = str(regime)
            rows.append(summary)
        table = pd.DataFrame(rows)
        if len(table) == 0:
            return table
        return table[["regime_label", "count", "roi", "realized_roi_pct", "avg_expected_profit", "avg_realized_profit", "calibration_gap", "market_bias", "variance", "drawdown", "survival_penalty"]].sort_values("roi", ascending=False).reset_index(drop=True)

    def profitability_heatmap(self, df: pd.DataFrame, xcol: str, ycol: str) -> pd.DataFrame:
        pivot = df.pivot_table(index=ycol, columns=xcol, values="realized_roi_pct", aggfunc="mean")
        return pivot.sort_index().sort_index(axis=1)

    def roi_curve(self, df: pd.DataFrame) -> pd.DataFrame:
        ordered = df.sort_values(["expected_value", "calibrated_probability", "pred_prob"], ascending=[False, False, False]).reset_index(drop=True)
        if len(ordered) == 0:
            return pd.DataFrame()

        rows = []
        for fraction in np.linspace(0.05, 1.0, self.config.top_curve_steps):
            n = max(1, int(len(ordered) * fraction))
            subset = ordered.iloc[:n]
            rows.append({
                "top_fraction": round(float(fraction), 3),
                "bets": int(n),
                "realized_roi_pct": round(float((subset["realized_profit"].sum() / subset["stake"].sum()) * 100.0) if subset["stake"].sum() > 0 else 0.0, 6),
                "expected_roi_pct": round(float(subset["expected_roi_pct"].mean()), 6),
                "avg_expected_profit": round(float(subset["expected_profit"].mean()), 6),
                "avg_realized_profit": round(float(subset["realized_profit"].mean()), 6),
                "drawdown": round(float(self._max_drawdown(subset["realized_profit"])), 6),
            })
        return pd.DataFrame(rows)

    def drawdown_report(self, df: pd.DataFrame) -> pd.DataFrame:
        curve = df["realized_profit"].fillna(0.0).cumsum()
        peak = curve.cummax()
        drawdown = curve - peak
        out = pd.DataFrame({
            "step": np.arange(len(df)),
            "equity": curve,
            "peak": peak,
            "drawdown": drawdown,
            "uncertainty_score": df["uncertainty_score"],
            "odds": df["odds"],
            "regime_label": df["regime_label"],
        })
        out["drawdown_pct"] = np.where(out["peak"] != 0, out["drawdown"] / out["peak"].replace(0, np.nan), 0.0)
        return out

    def survival_metrics(self, df: pd.DataFrame) -> Dict[str, object]:
        total_stake = float(df["stake"].sum())
        total_profit = float(df["realized_profit"].sum())
        exposure_adjusted_roi = total_profit / total_stake if total_stake > 0 else 0.0
        profit_series = df["realized_profit"].fillna(0.0)
        drawdown_series = profit_series.cumsum() - profit_series.cumsum().cummax()
        max_dd = float(drawdown_series.min()) if len(drawdown_series) else 0.0
        dd_p95 = float(np.quantile(drawdown_series, 0.05)) if len(drawdown_series) else 0.0
        dd_p99 = float(np.quantile(drawdown_series, 0.01)) if len(drawdown_series) else 0.0
        std = float(profit_series.std(ddof=0)) if len(profit_series) else 0.0
        mean = float(profit_series.mean()) if len(profit_series) else 0.0
        sharpe = mean / std if std > 0 else 0.0

        losses = (profit_series < 0).astype(int)
        max_lose_streak = 0
        current = 0
        for loss in losses:
            if loss:
                current += 1
                max_lose_streak = max(max_lose_streak, current)
            else:
                current = 0

        downside = profit_series[profit_series < 0]
        downside_std = float(downside.std(ddof=0)) if len(downside) > 0 else 0.0

        return {
            "total_bets": int(len(df)),
            "total_profit": round(total_profit, 6),
            "roi": round(total_profit / len(df), 6) if len(df) else 0.0,
            "exposure_adjusted_roi": round(exposure_adjusted_roi, 6),
            "max_drawdown": round(max_dd, 6),
            "drawdown_p95": round(dd_p95, 6),
            "drawdown_p99": round(dd_p99, 6),
            "volatility": round(std, 6),
            "downside_volatility": round(downside_std, 6),
            "sharpe_like": round(sharpe, 6),
            "max_lose_streak": int(max_lose_streak),
            "win_rate": round(float((profit_series > 0).mean()), 6),
            "stake_ratio_mean": round(float((df["stake"] / df["bankroll"].replace(0, np.nan)).fillna(0.0).mean()), 6) if "bankroll" in df.columns else None,
        }

    def calibration_vs_roi(self, df: pd.DataFrame) -> Dict[str, object]:
        calib_cols = [c for c in ["calibration_gap", "brier_score", "ece", "reliability", "drift_score", "uncertainty_score"] if c in df.columns]
        result = {}
        if len(df) > 1:
            for col in calib_cols:
                values = pd.to_numeric(df[col], errors="coerce")
                if values.notna().sum() > 1:
                    result[f"{col}_roi_corr"] = round(float(values.corr(df["realized_roi_pct"])), 6)

        if "calibration_gap" in df.columns:
            work = df.copy()
            work["calibration_bin"] = self._safe_cut(work["calibration_gap"], [0.0, 0.02, 0.05, 0.08, 0.12, 1.0]).astype(str)
            result["calibration_buckets"] = self.bucket_report(work, "calibration_bin").to_dict(orient="records")
        return result

    def expected_vs_realized(self, df: pd.DataFrame) -> Dict[str, object]:
        expected = df["expected_profit"].astype(float)
        realized = (df["realized_profit"] / df["stake"].replace(0, np.nan)).fillna(0.0)
        return {
            "ev_correlation": round(float(expected.corr(realized)), 6) if len(df) > 1 else 0.0,
            "ev_bias": round(float((expected - realized).mean()), 6),
            "ev_mae": round(float(np.mean(np.abs(expected - realized))), 6),
            "expected_mean": round(float(expected.mean()), 6),
            "realized_mean": round(float(realized.mean()), 6),
        }

    def diagnostic_flags(self, df: pd.DataFrame) -> Dict[str, object]:
        result = {
            "false_edge_zones": [],
            "favorite_bias": {},
            "longshot_bias": {},
            "unstable_roi_zones": [],
            "high_variance_traps": [],
        }

        if len(df) == 0:
            return result

        bucket_tables = {
            "odds": self.bucket_report(df, "odds_bin"),
            "confidence": self.bucket_report(df, "confidence_bin"),
            "edge": self.edge_quality_report(df),
            "uncertainty": self.bucket_report(df, "uncertainty_bin"),
            "regime": self.regime_profitability_report(df),
        }

        if len(bucket_tables["odds"]):
            worst = bucket_tables["odds"].sort_values(["roi", "variance"], ascending=[True, False]).head(3)
            result["false_edge_zones"] = worst.to_dict(orient="records")
            favorite = bucket_tables["odds"][bucket_tables["odds"]["odds_bin"].astype(str).str.contains("1.5", na=False)].head(1)
            if len(favorite):
                result["favorite_bias"] = favorite.iloc[0].to_dict()
            longshot = bucket_tables["odds"][bucket_tables["odds"]["odds_bin"].astype(str).str.contains("20|50", na=False)].head(1)
            if len(longshot):
                result["longshot_bias"] = longshot.iloc[0].to_dict()

        for table_name in ["confidence", "uncertainty"]:
            table = bucket_tables[table_name]
            if len(table):
                unstable = table[(table["roi"] < 0) & (table["variance"] > table["variance"].median())]
                if len(unstable):
                    result["unstable_roi_zones"].extend(unstable.to_dict(orient="records"))
                traps = table[(table["variance"] > table["variance"].quantile(0.75)) & (table["roi"] < 0)]
                if len(traps):
                    result["high_variance_traps"].extend(traps.to_dict(orient="records"))

        return result

    def overall_summary(self, df: pd.DataFrame, survival: Dict[str, object], calibration_roi: Dict[str, object], ev_report: Dict[str, object]) -> Dict[str, object]:
        total_bets = int(len(df))
        total_profit = float(df["realized_profit"].sum())
        stake = float(df["stake"].sum())
        roi = total_profit / stake if stake > 0 else 0.0

        summary = {
            "bets": total_bets,
            "stake": round(stake, 6),
            "profit": round(total_profit, 6),
            "exposure_adjusted_roi": round(roi, 6),
            "mean_odds": round(float(df["odds"].mean()), 6),
            "mean_pred_prob": round(float(df["pred_prob"].mean()), 6) if df["pred_prob"].notna().any() else None,
            "mean_uncertainty": round(float(df["uncertainty_score"].mean()), 6),
            "mean_expected_profit": round(float(df["expected_profit"].mean()), 6),
            "mean_realized_profit": round(float(df["realized_profit"].mean()), 6),
            "realized_roi_pct": round(float(roi * 100.0), 6),
            "survival_score": round(self._survival_score(survival), 6),
            "calibration_roi_links": calibration_roi,
            "ev_report": ev_report,
        }
        return summary

    def _survival_score(self, survival: Dict[str, object]) -> float:
        score = 1.0
        if survival.get("max_drawdown", 0.0) < -0.30:
            score *= 0.60
        elif survival.get("max_drawdown", 0.0) < -0.15:
            score *= 0.80

        if survival.get("volatility", 0.0) > 5.0:
            score *= 0.85

        if survival.get("sharpe_like", 0.0) < 0:
            score *= 0.75

        return float(max(0.0, min(1.0, score)))

    def _summarize_group(self, group: pd.DataFrame, label: str, key: str) -> dict:
        if len(group) == 0:
            return {}

        stake = float(group["stake"].sum())
        profit = float(group["realized_profit"].sum())
        roi = profit / stake if stake > 0 else 0.0
        variance = float(group["realized_profit"].var(ddof=0)) if len(group) > 1 else 0.0
        avg_expected = float(group["expected_profit"].mean())
        avg_realized = float(group["realized_profit"].mean())
        calibration_gap = float(group["calibration_gap"].mean()) if "calibration_gap" in group.columns else 0.0
        drawdown = float(self._max_drawdown(group["realized_profit"]))
        false_edge_rate = float(((group["expected_profit"] > 0) & (group["realized_profit"] <= 0)).mean())
        market_bias = float(group["market_bias"].mean()) if "market_bias" in group.columns else 0.0
        survival_penalty = self._bucket_survival_penalty(roi, drawdown, variance, false_edge_rate)

        return {
            label: key,
            "count": int(len(group)),
            "stake": round(stake, 6),
            "profit": round(profit, 6),
            "roi": round(roi, 6),
            "realized_roi_pct": round(roi * 100.0, 6),
            "avg_expected_profit": round(avg_expected, 6),
            "avg_realized_profit": round(avg_realized, 6),
            "variance": round(variance, 6),
            "drawdown": round(drawdown, 6),
            "calibration_gap": round(calibration_gap, 6),
            "market_bias": round(market_bias, 6),
            "false_edge_rate": round(false_edge_rate * 100.0, 6),
            "survival_penalty": round(survival_penalty, 6),
        }

    def _finalize_table(self, rows: List[dict], group_col: str) -> pd.DataFrame:
        table = pd.DataFrame([row for row in rows if row])
        if len(table) == 0:
            return table
        cols = [group_col, "count", "stake", "profit", "roi", "realized_roi_pct", "avg_expected_profit", "avg_realized_profit", "variance", "drawdown", "calibration_gap", "market_bias", "false_edge_rate", "survival_penalty"]
        existing = [c for c in cols if c in table.columns]
        return table[existing].sort_values([group_col, "count"], ascending=[True, False]).reset_index(drop=True)

    def _bucket_survival_penalty(self, roi: float, drawdown: float, variance: float, false_edge_rate: float) -> float:
        penalty = 1.0
        if roi < 0:
            penalty *= 0.70
        if drawdown < -0.15:
            penalty *= 0.80
        if drawdown < -0.30:
            penalty *= 0.60
        if variance > 1.0:
            penalty *= 0.85
        if false_edge_rate > 0.50:
            penalty *= 0.70
        return float(max(0.0, min(1.0, penalty)))

    def _max_drawdown(self, profits: pd.Series) -> float:
        equity = profits.fillna(0.0).cumsum()
        peak = equity.cummax()
        drawdown = equity - peak
        return float(drawdown.min()) if len(drawdown) else 0.0

    def _regime_or_market(self, df: pd.DataFrame) -> pd.Series:
        return df["regime_label"].fillna(df["market_regime"])


def save_report_artifacts(report: Dict[str, object], outdir: str | Path) -> None:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    def save_table(name: str, value):
        if isinstance(value, pd.DataFrame):
            value.to_csv(outdir / f"{name}.csv", index=True if value.index.name else False, encoding="utf-8-sig")
        elif isinstance(value, dict):
            (outdir / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    save_table("overall", pd.DataFrame([report.get("overall", {})]))
    save_table("odds_table", report.get("odds_table", pd.DataFrame()))
    save_table("confidence_table", report.get("confidence_table", pd.DataFrame()))
    save_table("edge_table", report.get("edge_table", pd.DataFrame()))
    save_table("uncertainty_table", report.get("uncertainty_table", pd.DataFrame()))
    save_table("regime_table", report.get("regime_table", pd.DataFrame()))
    save_table("heatmap_odds_uncertainty", report.get("heatmap_odds_uncertainty", pd.DataFrame()))
    save_table("heatmap_confidence_edge", report.get("heatmap_confidence_edge", pd.DataFrame()))
    save_table("roi_curve", report.get("roi_curve", pd.DataFrame()))
    save_table("drawdown_report", report.get("drawdown_report", pd.DataFrame()))
    save_table("survival", pd.DataFrame([report.get("survival", {})]))
    save_table("calibration_roi", pd.DataFrame([report.get("calibration_roi", {})]))
    save_table("expected_vs_realized", pd.DataFrame([report.get("expected_vs_realized", {})]))
    save_table("diagnostics", pd.DataFrame([report.get("diagnostics", {})]))


def plot_heatmap(matrix: pd.DataFrame, title: str, outpath: Path) -> None:
    if matrix is None or len(matrix) == 0:
        return

    fig, ax = plt.subplots(figsize=(12, 8))
    data = matrix.copy()
    numeric = data.apply(pd.to_numeric, errors="coerce")
    im = ax.imshow(numeric.to_numpy(dtype=float), aspect="auto", cmap="RdYlGn", interpolation="nearest")
    ax.set_title(title)
    ax.set_xticks(range(len(numeric.columns)))
    ax.set_xticklabels([str(c) for c in numeric.columns], rotation=45, ha="right")
    ax.set_yticks(range(len(numeric.index)))
    ax.set_yticklabels([str(i) for i in numeric.index])
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(outpath, dpi=160)
    plt.close(fig)


def plot_roi_curve(curve: pd.DataFrame, outpath: Path) -> None:
    if curve is None or len(curve) == 0:
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(curve["top_fraction"], curve["realized_roi_pct"], marker="o", linewidth=2, label="Realized")
    ax.plot(curve["top_fraction"], curve["expected_roi_pct"], marker="s", linewidth=2, label="Expected")
    ax.axhline(0.0, color="gray", linestyle="--", linewidth=1)
    ax.set_xlabel("Top fraction of bets")
    ax.set_ylabel("ROI (%)")
    ax.set_title("ROI Curve")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(outpath, dpi=160)
    plt.close(fig)


def plot_drawdown(drawdown_report: pd.DataFrame, outpath: Path) -> None:
    if drawdown_report is None or len(drawdown_report) == 0:
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(drawdown_report["step"], drawdown_report["equity"], linewidth=2, label="Equity")
    ax.fill_between(drawdown_report["step"], drawdown_report["drawdown"], 0, alpha=0.25, label="Drawdown")
    ax.set_xlabel("Bet index")
    ax.set_ylabel("Cumulative profit")
    ax.set_title("Drawdown Curve")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(outpath, dpi=160)
    plt.close(fig)