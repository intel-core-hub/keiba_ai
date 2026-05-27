import math
from typing import Dict
import numpy as np
import pandas as pd


def _shannon_entropy(probs: np.ndarray) -> float:
    probs = np.asarray(probs, dtype=float)
    probs = probs[probs > 0]
    if probs.size == 0:
        return 0.0
    return -float((probs * np.log(probs)).sum())


def _gini(array: np.ndarray) -> float:
    # Gini coefficient for inequality (0..1)
    array = np.asarray(array, dtype=float)
    if array.size == 0:
        return 0.0
    array = np.sort(array)
    n = array.size
    cum = np.cumsum(array, dtype=float)
    if cum[-1] == 0:
        return 0.0
    gini = (2.0 * np.sum((np.arange(1, n + 1) * array))) / (n * cum[-1]) - (n + 1) / n
    return float(gini)


def compute_race_metrics(
    runners: pd.DataFrame,
    *,
    odds_col: str = "odds",
    prob_col: str = "implied_prob",
    uncertainty_col: str = "model_uncertainty",
    edge_col: str = "edge",
    hit_col: str = "hit",
    profit_col: str = "profit",
    stake_col: str = "stake",
) -> Dict:
    """
    Compute explainable market metrics for a single race.

    runners: DataFrame with one row per runner. Should contain either `odds` or `implied_prob`.
    Returns a dict of metrics used for regime detection.
    """
    metrics = {}

    # Odds / implied prob handling
    if prob_col in runners.columns and not runners[prob_col].isna().all():
        probs = runners[prob_col].fillna(0).astype(float).values
        # normalize if needed
        s = probs.sum()
        if s <= 0:
            probs = np.ones_like(probs) / len(probs)
        else:
            probs = probs / s
        odds = np.where(probs > 0, 1.0 / probs, np.nan)
    elif odds_col in runners.columns and not runners[odds_col].isna().all():
        odds = runners[odds_col].replace([np.inf, -np.inf], np.nan).astype(float).values
        # implied prob from odds (ignoring overround)
        with np.errstate(divide='ignore', invalid='ignore'):
            probs = np.where(np.isfinite(odds) & (odds > 0), 1.0 / odds, 0.0)
        s = probs.sum()
        if s > 0:
            probs = probs / s
        else:
            probs = np.ones_like(probs) / len(probs)
    else:
        # no odds/prob info
        probs = np.ones((len(runners),)) / max(1, len(runners))
        odds = np.where(probs > 0, 1.0 / probs, np.nan)

    metrics["num_runners"] = int(len(runners))
    metrics["mean_odds"] = float(np.nanmean(odds)) if len(odds) else float('nan')
    metrics["median_odds"] = float(np.nanmedian(odds)) if len(odds) else float('nan')
    metrics["odds_skew"] = float(pd.Series(odds).skew())
    metrics["odds_kurtosis"] = float(pd.Series(odds).kurt())

    # favorite concentration
    sorted_idx = np.argsort(-probs)
    top1 = probs[sorted_idx[0]] if len(probs) > 0 else 0.0
    top3 = probs[sorted_idx[:3]].sum() if len(probs) >= 3 else probs.sum()
    metrics["fav_top1"] = float(top1)
    metrics["fav_top3_share"] = float(top3)

    # payout / return volatility proxy: use implied payout dispersion
    payout_std = float(np.nanstd(odds)) if len(odds) else 0.0
    metrics["payout_std"] = float(0.0 if np.isnan(payout_std) else payout_std)
    metrics["payout_volatility"] = metrics["payout_std"]

    # edge features are required for edge decay / market efficiency monitoring
    if edge_col in runners.columns:
        edge = pd.to_numeric(runners[edge_col], errors="coerce").fillna(0.0).astype(float).values
        metrics["edge_mean"] = float(np.mean(edge)) if len(edge) else 0.0
        metrics["edge_std"] = float(np.std(edge)) if len(edge) else 0.0
        metrics["edge_abs_mean"] = float(np.mean(np.abs(edge))) if len(edge) else 0.0
        metrics["edge_positive_rate"] = float(np.mean(edge > 0.0)) if len(edge) else 0.0
    else:
        metrics["edge_mean"] = 0.0
        metrics["edge_std"] = 0.0
        metrics["edge_abs_mean"] = 0.0
        metrics["edge_positive_rate"] = 0.0

    # liquidity proxy
    if "total_pool" in runners.columns:
        metrics["liquidity_proxy"] = float(runners["total_pool"].iloc[0])
        metrics["liquidity_volatility"] = float(pd.to_numeric(runners["total_pool"], errors="coerce").std())
    elif "volume" in runners.columns:
        metrics["liquidity_proxy"] = float(runners["volume"].sum())
        metrics["liquidity_volatility"] = float(pd.to_numeric(runners["volume"], errors="coerce").std())
    else:
        # fallback: inverse of variance of odds (higher variance => lower liquidity)
        var = float(np.nanvar(odds))
        metrics["liquidity_proxy"] = float(1.0 / (1e-6 + var))
        metrics["liquidity_volatility"] = 0.0

    # uncertainty
    if uncertainty_col in runners.columns:
        metrics["uncertainty_mean"] = float(runners[uncertainty_col].astype(float).mean())
        metrics["uncertainty_std"] = float(runners[uncertainty_col].astype(float).std())
        metrics["uncertainty_proxy"] = float(metrics["uncertainty_mean"])
    else:
        metrics["uncertainty_mean"] = float(0.0)
        metrics["uncertainty_std"] = float(0.0)

    # calibration metrics if outcomes are available
    if prob_col in runners.columns and hit_col in runners.columns:
        prob = pd.to_numeric(runners[prob_col], errors="coerce").fillna(0.0).astype(float).values
        hit = pd.to_numeric(runners[hit_col], errors="coerce").fillna(0.0).astype(float).values
        if len(prob) and len(hit):
            metrics["calibration_gap"] = float(abs(float(np.mean(prob)) - float(np.mean(hit))))
            metrics["brier_score"] = float(np.mean((prob - hit) ** 2))
            metrics["reliability_error"] = float(np.mean(np.abs(prob - hit)))
        else:
            metrics["calibration_gap"] = 0.0
            metrics["brier_score"] = 0.0
            metrics["reliability_error"] = 0.0
    else:
        metrics["calibration_gap"] = 0.0
        metrics["brier_score"] = 0.0
        metrics["reliability_error"] = 0.0

    if uncertainty_col not in runners.columns:
        uncertainty_proxy = min(1.0, metrics["calibration_gap"] + 0.5 * metrics["edge_abs_mean"])
        metrics["uncertainty_proxy"] = float(uncertainty_proxy)
        metrics["uncertainty_mean"] = float(uncertainty_proxy)
        metrics["uncertainty_std"] = 0.0

    if profit_col in runners.columns:
        profit = pd.to_numeric(runners[profit_col], errors="coerce").fillna(0.0).astype(float).values
        metrics["profit_mean"] = float(np.mean(profit)) if len(profit) else 0.0
        metrics["profit_std"] = float(np.std(profit)) if len(profit) else 0.0
    else:
        metrics["profit_mean"] = 0.0
        metrics["profit_std"] = 0.0

    if stake_col in runners.columns:
        stake = pd.to_numeric(runners[stake_col], errors="coerce").fillna(0.0).astype(float).values
        metrics["stake_mean"] = float(np.mean(stake)) if len(stake) else 0.0
        metrics["stake_std"] = float(np.std(stake)) if len(stake) else 0.0
    else:
        metrics["stake_mean"] = 0.0
        metrics["stake_std"] = 0.0

    # entropy
    metrics["entropy"] = float(_shannon_entropy(probs))

    # gini / chaos
    metrics["gini"] = float(_gini(probs))
    # chaos index: combination of entropy and payout dispersion
    metrics["chaos_index"] = float(metrics["entropy"] * metrics["payout_std"])
    metrics["market_efficiency_proxy"] = float(1.0 / (1.0 + metrics["edge_abs_mean"] + metrics["calibration_gap"] + metrics["payout_std"] * 0.01))

    return metrics


def batch_compute_metrics(df: pd.DataFrame, race_id_col: str = "race_id", **kwargs) -> pd.DataFrame:
    """
    Given a DataFrame containing many runners across races, compute metrics per race.
    Returns a DataFrame indexed by race_id with metric columns.
    """
    records = []
    for race_id, grp in df.groupby(race_id_col):
        m = compute_race_metrics(grp, **kwargs)
        m.update({"race_id": race_id})
        records.append(m)
    return pd.DataFrame.from_records(records).set_index("race_id")
