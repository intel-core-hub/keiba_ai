from typing import Dict, Optional
import numpy as np
try:
    import pandas as pd
except Exception:
    pd = None
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler


def rule_based_regime(metrics: Dict) -> str:
    """Simple explainable rules to assign a regime label from metrics."""
    # thresholds are intentionally conservative and tunable
    entropy = metrics.get("entropy", 0.0)
    fav_top1 = metrics.get("fav_top1", 0.0)
    fav_top3 = metrics.get("fav_top3_share", 0.0)
    payout_std = metrics.get("payout_std", 0.0)
    liquidity = metrics.get("liquidity_proxy", 0.0)
    liquidity_volatility = metrics.get("liquidity_volatility", 0.0)
    uncertainty = metrics.get("uncertainty_mean", 0.0)
    gini = metrics.get("gini", 0.0)
    calibration_gap = metrics.get("calibration_gap", 0.0)
    brier_score = metrics.get("brier_score", 0.0)
    reliability_error = metrics.get("reliability_error", 0.0)
    edge_mean = metrics.get("edge_mean", 0.0)
    edge_abs_mean = metrics.get("edge_abs_mean", abs(edge_mean))
    payout_volatility = metrics.get("payout_volatility", payout_std)
    market_efficiency_proxy = metrics.get("market_efficiency_proxy", 0.0)
    roi = metrics.get("roi", metrics.get("ROI", 0.0))
    drawdown = metrics.get("drawdown", metrics.get("max_drawdown", 0.0))
    num_runners = int(metrics.get("num_runners", 0) or 0)

    # If input metrics are derived from a single-row dataset (e.g. backtest outputs
    # that only include recommended horses), we cannot compute meaningful market
    # regime labels based on concentration metrics. Return 'unknown' to signal
    # that full-card metrics are required.
    if num_runners <= 1:
        return "unknown"

    # Uncertainty storm takes precedence
    if uncertainty > 0.5 and (calibration_gap > 0.08 or drawdown > 0.05):
        return "uncertainty_storm"

    if uncertainty > 0.45 and calibration_gap > 0.12:
        return "uncertainty_storm"

    # Calibration collapse
    if calibration_gap > 0.15 and (brier_score > 0.08 or reliability_error > 0.12):
        return "calibration_collapse"

    # Low liquidity
    if liquidity < 1e-2 or (liquidity > 0 and liquidity_volatility > liquidity * 0.3):
        return "unstable_liquidity"

    # Favorite-heavy: very concentrated mass on top
    if fav_top1 > 0.5 or fav_top3 > 0.82 or gini > 0.6:
        return "favorite_distortion"

    # Market efficiency spike: edge gets thin and market becomes harder to exploit
    if market_efficiency_proxy > 0.6 and edge_abs_mean < 0.02 and calibration_gap < 0.08:
        return "market_efficiency_spike"

    # Chaotic: high entropy + high payout dispersion
    if entropy > 1.5 and payout_std > 5.0:
        return "high_payout_volatility"

    # Edge deterioration: current edge is thin and performance is weak
    if edge_mean < 0.01 and edge_abs_mean < 0.025 and roi <= 0.0:
        return "edge_deterioration"

    # High variance / payout volatility
    if payout_std > 8.0 or payout_volatility > 8.0:
        return "high_payout_volatility"

    # Distorted market: low entropy but high payout_std (odds disagrees)
    if entropy < 0.5 and payout_std > 4.0:
        return "favorite_distortion"

    # Stable default
    return "stable_market"


class ClusterRegimeDetector:
    """KMeans-based clustering over metric vectors with a scaler.

    This is provided as an optional, still explainable approach: map cluster ids to labels
    via inspection or small rule set.
    """

    def __init__(self, n_clusters: int = 4, random_state: int = 42):
        self.n_clusters = n_clusters
        self.random_state = random_state
        self.scaler = StandardScaler()
        self.km: Optional[KMeans] = None

    def fit(self, metrics_df: pd.DataFrame):
        X = metrics_df.fillna(0).values
        Xs = self.scaler.fit_transform(X)
        self.km = KMeans(n_clusters=self.n_clusters, random_state=self.random_state)
        self.km.fit(Xs)
        return self

    def predict(self, metrics_df: pd.DataFrame) -> np.ndarray:
        if self.km is None:
            raise RuntimeError("ClusterRegimeDetector not fitted")
        X = metrics_df.fillna(0).values
        Xs = self.scaler.transform(X)
        return self.km.predict(Xs)
