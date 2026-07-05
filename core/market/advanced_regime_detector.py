from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

import numpy as np
try:
    import pandas as pd
except Exception:
    pd = None

from .regime_metrics import batch_compute_metrics


def _value(metrics: Dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(metrics.get(key, default) or default)
    except Exception:
        return float(default)


def _scale(value: float, low: float, high: float, *, reverse: bool = False) -> float:
    if np.isnan(value):
        return 0.0
    if high == low:
        return 0.0
    if reverse:
        value = high - (value - low)
        low, high = low, high
    score = (value - low) / (high - low)
    return float(np.clip(score, 0.0, 1.0))


@dataclass
class RegimeThresholds:
    uncertainty_high: float = 0.55
    calibration_high: float = 0.10
    edge_low: float = 0.012
    payout_high: float = 6.0
    liquidity_low: float = 0.08
    favorite_top1_high: float = 0.45
    favorite_top3_high: float = 0.78
    gini_high: float = 0.58
    score_threshold: float = 1.2


class AdvancedRegimeDetector:
    """Explainable regime detector for market structure change.

    The detector avoids clustering and deep latent states. It scores transparent
    feature groups and returns the highest-confidence regime.
    """

    REGIME_PRIORITY = [
        "uncertainty_storm",
        "calibration_collapse",
        "unstable_liquidity",
        "high_payout_volatility",
        "market_efficiency_spike",
        "edge_deterioration",
        "favorite_distortion",
        "stable_market",
    ]

    def __init__(self, window_size: int = 20, thresholds: Optional[RegimeThresholds] = None):
        self.window_size = int(window_size)
        self.thresholds = thresholds or RegimeThresholds()
        self.history: Deque[Dict[str, float]] = deque(maxlen=self.window_size)
        self.last_features: Dict[str, float] = {}
        self.last_scores: Dict[str, float] = {}
        self.last_regime: str = "stable_market"

    def _baseline(self, key: str) -> float:
        values = [float(item.get(key, 0.0)) for item in self.history if key in item]
        if not values:
            return 0.0
        return float(np.mean(values))

    def expand_features(self, metrics: Dict[str, Any]) -> Dict[str, float]:
        current = {
            "payout_std": _value(metrics, "payout_std"),
            "payout_volatility": _value(metrics, "payout_volatility", _value(metrics, "payout_std")),
            "edge_mean": _value(metrics, "edge_mean"),
            "edge_std": _value(metrics, "edge_std"),
            "edge_abs_mean": _value(metrics, "edge_abs_mean", abs(_value(metrics, "edge_mean"))),
            "edge_positive_rate": _value(metrics, "edge_positive_rate"),
            "calibration_gap": _value(metrics, "calibration_gap"),
            "brier_score": _value(metrics, "brier_score"),
            "reliability_error": _value(metrics, "reliability_error"),
            "uncertainty_mean": _value(metrics, "uncertainty_mean"),
            "uncertainty_std": _value(metrics, "uncertainty_std"),
            "liquidity_proxy": _value(metrics, "liquidity_proxy"),
            "liquidity_volatility": _value(metrics, "liquidity_volatility"),
            "fav_top1": _value(metrics, "fav_top1"),
            "fav_top3_share": _value(metrics, "fav_top3_share"),
            "gini": _value(metrics, "gini"),
            "entropy": _value(metrics, "entropy"),
            "roi": _value(metrics, "roi", _value(metrics, "ROI")),
            "drawdown": _value(metrics, "drawdown", _value(metrics, "max_drawdown")),
            "market_efficiency_proxy": _value(metrics, "market_efficiency_proxy"),
        }

        baseline_payout = self._baseline("payout_std")
        baseline_edge = self._baseline("edge_mean")
        baseline_calibration = self._baseline("calibration_gap")
        baseline_uncertainty = self._baseline("uncertainty_mean")
        baseline_liquidity = self._baseline("liquidity_proxy")
        baseline_roi = self._baseline("roi")

        features = dict(current)
        features.update({
            "payout_volatility_ratio": float(current["payout_std"] / baseline_payout) if baseline_payout > 0 else float(current["payout_std"]),
            "edge_decay": float(max(0.0, baseline_edge - current["edge_mean"])),
            "edge_shift": float(current["edge_mean"] - baseline_edge),
            "calibration_spike": float(max(0.0, current["calibration_gap"] - baseline_calibration)),
            "uncertainty_spike": float(max(0.0, current["uncertainty_mean"] - baseline_uncertainty)),
            "liquidity_drop": float(max(0.0, baseline_liquidity - current["liquidity_proxy"])),
            "liquidity_ratio": float(current["liquidity_proxy"] / baseline_liquidity) if baseline_liquidity > 0 else float(current["liquidity_proxy"]),
            "roi_decay": float(max(0.0, baseline_roi - current["roi"])),
            "favorite_pressure": float(current["fav_top1"] + current["fav_top3_share"] + current["gini"]),
            "efficiency_gap": float(1.0 - current["market_efficiency_proxy"]),
            "baseline_payout_std": float(baseline_payout),
            "baseline_calibration_gap": float(baseline_calibration),
            "baseline_uncertainty": float(baseline_uncertainty),
            "baseline_liquidity": float(baseline_liquidity),
        })
        return features

    def score_regimes(self, features: Dict[str, float]) -> Dict[str, float]:
        t = self.thresholds
        scores = {
            "uncertainty_storm": (
                _scale(features["uncertainty_mean"], t.uncertainty_high, 0.85)
                + _scale(features["calibration_gap"], t.calibration_high, 0.18)
                + _scale(features["uncertainty_spike"], 0.05, 0.15)
            ),
            "calibration_collapse": (
                _scale(features["calibration_gap"], t.calibration_high, 0.22)
                + _scale(features["brier_score"], 0.05, 0.16)
                + _scale(features["reliability_error"], 0.05, 0.18)
            ),
            "unstable_liquidity": (
                _scale(features["liquidity_drop"], 0.0, 0.25 * max(features["baseline_liquidity"], 1.0))
                + _scale(features["liquidity_ratio"], 0.8, 0.35, reverse=True)
                + _scale(features["liquidity_volatility"], 0.0, max(features["baseline_liquidity"] * 0.1, 1.0))
            ),
            "high_payout_volatility": (
                _scale(features["payout_volatility_ratio"], 1.1, 1.6)
                + _scale(features["payout_std"], t.payout_high, t.payout_high * 2.0)
            ),
            "market_efficiency_spike": (
                _scale(features["market_efficiency_proxy"], 0.55, 0.85)
                + _scale(features["edge_abs_mean"], t.edge_low * 2.0, t.edge_low, reverse=True)
                + _scale(features["calibration_gap"], t.calibration_high, 0.02, reverse=True)
            ),
            "edge_deterioration": (
                _scale(features["edge_decay"], 0.0, 0.03)
                + _scale(features["roi_decay"], 0.0, 0.08)
                + _scale(features["edge_abs_mean"], t.edge_low * 2.0, t.edge_low, reverse=True)
            ),
            "favorite_distortion": (
                _scale(features["fav_top1"], t.favorite_top1_high, 0.6)
                + _scale(features["fav_top3_share"], t.favorite_top3_high, 0.9)
                + _scale(features["gini"], t.gini_high, 0.8)
            ),
            "stable_market": 0.0,
        }
        return {key: float(max(0.0, value)) for key, value in scores.items()}

    def detect(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        features = self.expand_features(metrics)
        scores = self.score_regimes(features)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], self.REGIME_PRIORITY.index(item[0])))
        regime, regime_score = ranked[0]
        if regime_score < self.thresholds.score_threshold:
            regime = "stable_market"

        result = {
            "regime": regime,
            "regime_score": float(regime_score),
            "scores": scores,
            "features": features,
            "reasons": self.explain(features, scores, regime),
        }

        self.last_regime = regime
        self.last_features = features
        self.last_scores = scores

        self.history.append({
            "payout_std": features["payout_std"],
            "edge_mean": features["edge_mean"],
            "calibration_gap": features["calibration_gap"],
            "uncertainty_mean": features["uncertainty_mean"],
            "liquidity_proxy": features["liquidity_proxy"],
            "roi": features["roi"],
        })
        return result

    def explain(self, features: Dict[str, float], scores: Dict[str, float], regime: str) -> List[str]:
        reasons: List[str] = []
        if regime == "uncertainty_storm":
            reasons.append(f"uncertainty_mean={features['uncertainty_mean']:.4f}")
            reasons.append(f"calibration_gap={features['calibration_gap']:.4f}")
        elif regime == "calibration_collapse":
            reasons.append(f"calibration_gap={features['calibration_gap']:.4f}")
            reasons.append(f"brier_score={features['brier_score']:.4f}")
        elif regime == "unstable_liquidity":
            reasons.append(f"liquidity_proxy={features['liquidity_proxy']:.4f}")
            reasons.append(f"liquidity_drop={features['liquidity_drop']:.4f}")
        elif regime == "high_payout_volatility":
            reasons.append(f"payout_std={features['payout_std']:.4f}")
            reasons.append(f"payout_volatility_ratio={features['payout_volatility_ratio']:.4f}")
        elif regime == "market_efficiency_spike":
            reasons.append(f"market_efficiency_proxy={features['market_efficiency_proxy']:.4f}")
            reasons.append(f"edge_abs_mean={features['edge_abs_mean']:.4f}")
        elif regime == "edge_deterioration":
            reasons.append(f"edge_decay={features['edge_decay']:.4f}")
            reasons.append(f"roi_decay={features['roi_decay']:.4f}")
        elif regime == "favorite_distortion":
            reasons.append(f"fav_top1={features['fav_top1']:.4f}")
            reasons.append(f"gini={features['gini']:.4f}")
        else:
            reasons.append("baseline conditions within thresholds")
        reasons.append(f"score={scores.get(regime, 0.0):.4f}")
        return reasons

    def detect_series(self, metrics_df: pd.DataFrame, *, order_col: Optional[str] = None, race_id_col: str = "race_id") -> pd.DataFrame:
        if metrics_df is None or len(metrics_df) == 0:
            return pd.DataFrame()

        work = metrics_df.copy()
        if order_col and order_col in work.columns:
            work = work.sort_values(order_col)

        records: List[Dict[str, Any]] = []
        for index, row in work.iterrows():
            metrics = row.to_dict()
            outcome = self.detect(metrics)
            record = {
                "row_index": index,
                race_id_col: metrics.get(race_id_col, index),
                "regime": outcome["regime"],
                "regime_score": outcome["regime_score"],
                "reasons": " | ".join(outcome["reasons"]),
            }
            record.update({f"score_{key}": value for key, value in outcome["scores"].items()})
            record.update({f"feature_{key}": value for key, value in outcome["features"].items()})
            records.append(record)

        result = pd.DataFrame.from_records(records)
        if race_id_col in work.columns:
            result[race_id_col] = result[race_id_col].values
        return result

    def detect_from_raw(self, df: pd.DataFrame, *, race_id_col: str = "race_id", order_col: Optional[str] = None, **kwargs) -> pd.DataFrame:
        metrics_df = batch_compute_metrics(df, race_id_col=race_id_col, **kwargs).reset_index()
        return self.detect_series(metrics_df, order_col=order_col, race_id_col=race_id_col)
