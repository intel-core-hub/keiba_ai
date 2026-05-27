# learning/uncertainty.py
#
# Lightweight uncertainty estimation utilities for binary probability forecasts.

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

EPS = 1e-6
DEFAULT_BINS = np.linspace(0.0, 1.0, 11)


def clip_probabilities(probabilities):
    return np.clip(np.asarray(probabilities, dtype=float), EPS, 1.0 - EPS)


def normalized_entropy(probability: float) -> float:
    p = float(np.clip(probability, EPS, 1.0 - EPS))
    entropy = -(p * math.log(p) + (1.0 - p) * math.log(1.0 - p))
    return float(entropy / math.log(2.0))


def _bin_index(probability: float, bins=None) -> int:
    edges = np.asarray(bins if bins is not None else DEFAULT_BINS, dtype=float)
    p = float(np.clip(probability, 0.0, 1.0))
    idx = int(np.searchsorted(edges, p, side="right") - 1)
    return max(0, min(idx, len(edges) - 2))


def _bootstrap_hit_std(hits: np.ndarray, bootstrap_samples: int, rng: np.random.Generator) -> float:
    if len(hits) == 0:
        return 0.0
    if len(hits) == 1:
        return 0.0

    samples = []
    for _ in range(bootstrap_samples):
        sample = rng.choice(hits, size=len(hits), replace=True)
        samples.append(float(np.mean(sample)))

    return float(np.std(samples))


def build_uncertainty_profile(
    probabilities,
    hits,
    bins=10,
    bootstrap_samples=200,
    random_state=42,
):
    """
    Build a compact, serializable uncertainty profile from validation predictions.

    The profile stores per-bin calibration gaps and uncertainty widths so that
    prediction-time betting can abstain on high-uncertainty cases without fitting
    a new model.
    """
    probs = clip_probabilities(probabilities)
    hits = np.asarray(hits, dtype=float)
    if len(probs) != len(hits):
        raise ValueError("probabilities and hits must have the same length")

    edges = np.linspace(0.0, 1.0, bins + 1)
    rng = np.random.default_rng(random_state)
    records = []

    for idx, (lower, upper) in enumerate(zip(edges[:-1], edges[1:])):
        if upper == 1.0:
            mask = (probs >= lower) & (probs <= upper)
        else:
            mask = (probs >= lower) & (probs < upper)

        count = int(mask.sum())
        if count == 0:
            continue

        bin_probs = probs[mask]
        bin_hits = hits[mask]
        avg_prob = float(bin_probs.mean())
        actual_rate = float(bin_hits.mean())
        abs_error = np.abs(bin_probs - bin_hits)
        entropy_values = np.asarray([normalized_entropy(p) for p in bin_probs], dtype=float)
        bootstrap_std = _bootstrap_hit_std(bin_hits, bootstrap_samples, rng)

        records.append({
            "bin_index": idx,
            "lower": round(float(lower), 6),
            "upper": round(float(upper), 6),
            "label": f"{lower:.1f}-{upper:.1f}",
            "count": count,
            "avg_prob": round(avg_prob, 6),
            "actual_rate": round(actual_rate, 6),
            "calibration_gap": round(abs(avg_prob - actual_rate), 6),
            "entropy_mean": round(float(entropy_values.mean()), 6),
            "entropy_std": round(float(entropy_values.std()), 6),
            "abs_error_mean": round(float(abs_error.mean()), 6),
            "abs_error_q90": round(float(np.quantile(abs_error, 0.9)), 6),
            "bootstrap_hit_std": round(float(bootstrap_std), 6),
            "conformal_width": round(float(np.quantile(abs_error, 0.9)), 6),
        })

    if not records:
        overall = {
            "count": 0,
            "avg_prob": 0.0,
            "actual_rate": 0.0,
            "calibration_gap": 0.0,
            "entropy_mean": 0.0,
            "abs_error_mean": 0.0,
            "abs_error_q90": 0.25,
            "bootstrap_hit_std": 0.0,
            "conformal_width": 0.25,
        }
        return {
            "bins": [],
            "overall": overall,
            "recommended_max_uncertainty": 0.5,
            "quantile_alpha": 0.1,
            "bins_count": bins,
        }

    frame = pd.DataFrame(records)
    overall = {
        "count": int(len(probs)),
        "avg_prob": round(float(probs.mean()), 6),
        "actual_rate": round(float(hits.mean()), 6),
        "calibration_gap": round(float(abs(probs.mean() - hits.mean())), 6),
        "entropy_mean": round(float(np.mean([normalized_entropy(p) for p in probs])), 6),
        "abs_error_mean": round(float(np.mean(np.abs(probs - hits))), 6),
        "abs_error_q90": round(float(np.quantile(np.abs(probs - hits), 0.9)), 6),
        "bootstrap_hit_std": round(float(_bootstrap_hit_std(hits, bootstrap_samples, rng)), 6),
        "conformal_width": round(float(np.quantile(np.abs(probs - hits), 0.9)), 6),
    }

    # A practical betting gate: keep the lower-uncertainty 80% of the calibration profile.
    recommended = float(np.quantile(frame["entropy_mean"].to_numpy(dtype=float), 0.8))

    return {
        "bins": frame.to_dict(orient="records"),
        "overall": overall,
        "recommended_max_uncertainty": round(recommended, 6),
        "quantile_alpha": 0.1,
        "bins_count": bins,
    }


def estimate_uncertainty(probability: float, profile: dict | None = None) -> dict:
    p = float(np.clip(probability, EPS, 1.0 - EPS))
    entropy = normalized_entropy(p)
    base_width = 0.25
    bootstrap_std = 0.0
    conformal_width = base_width
    calibration_gap = 0.0
    bin_label = "fallback"

    if profile and profile.get("bins"):
        edges = profile.get("bins_count", 10)
        bins = np.linspace(0.0, 1.0, int(edges) + 1)
        idx = _bin_index(p, bins=bins)
        for row in profile["bins"]:
            if int(row.get("bin_index", -1)) == idx:
                bootstrap_std = float(row.get("bootstrap_hit_std", 0.0) or 0.0)
                conformal_width = float(row.get("conformal_width", base_width) or base_width)
                calibration_gap = float(row.get("calibration_gap", 0.0) or 0.0)
                bin_label = str(row.get("label", idx))
                break
        else:
            overall = profile.get("overall", {})
            bootstrap_std = float(overall.get("bootstrap_hit_std", 0.0) or 0.0)
            conformal_width = float(overall.get("conformal_width", base_width) or base_width)
            calibration_gap = float(overall.get("calibration_gap", 0.0) or 0.0)
    else:
        bin_label = f"{_bin_index(p):02d}"

    entropy_norm = entropy
    bootstrap_norm = float(np.clip(bootstrap_std / 0.25, 0.0, 1.0))
    conformal_norm = float(np.clip(conformal_width / 0.5, 0.0, 1.0))
    score = 0.5 * entropy_norm + 0.25 * bootstrap_norm + 0.25 * conformal_norm
    score = float(np.clip(score, 0.0, 1.0))

    lower = float(np.clip(p - conformal_width, 0.0, 1.0))
    upper = float(np.clip(p + conformal_width, 0.0, 1.0))

    return {
        "entropy": round(float(entropy_norm), 6),
        "bootstrap_std": round(float(bootstrap_std), 6),
        "conformal_width": round(float(conformal_width), 6),
        "calibration_gap": round(float(calibration_gap), 6),
        "uncertainty_score": round(float(score), 6),
        "prediction_interval_low": round(lower, 6),
        "prediction_interval_high": round(upper, 6),
        "prediction_interval_width": round(float(upper - lower), 6),
        "bin_label": bin_label,
        "bet_eligible": score <= (profile.get("recommended_max_uncertainty", 0.65) if profile else 0.65),
    }
