"""
Feature precompute utilities.

Provide a small API to compute per-horse feature dicts for a race and
store them in a LatestResultCache under key `features:{race_id}`.

This module keeps implementation minimal and safe for production critical path.
"""
from typing import Any, Dict
import time


def _row_to_features(row: Dict[str, Any]) -> Dict[str, Any]:
    # Best-effort extraction of numeric fields and simple engineered features.
    features = {}
    try:
        # copy numeric-like values
        for k, v in row.items():
            if v is None:
                continue
            try:
                f = float(v)
                features[k] = f
            except Exception:
                # keep some known fields as-is
                if k in {"horse_id", "horse_name", "selection"}:
                    features[k] = v
    except Exception:
        pass

    # example engineered features (safe defaults)
    if "speed_index" in features and "recent_form_score" in features:
        try:
            features["form_speed_interaction"] = features.get("speed_index", 0.0) * (features.get("recent_form_score", 0.0) + 1.0)
        except Exception:
            pass

    return features


def precompute_for_race(race_id: str, rows: Any, cache) -> Dict[str, Dict[str, Any]]:
    """Compute features for a race.

    rows: iterable of row mappings (dict-like)
    cache: LatestResultCache instance

    Returns mapping selection -> features
    """
    feat_map = {}
    for row in rows:
        selection = row.get("selection") or row.get("horse_id") or str(row.get("number"))
        features = _row_to_features(row)
        feat_map[selection] = features

    key = f"features:{race_id}"
    cache.put(key, feat_map)
    return feat_map
