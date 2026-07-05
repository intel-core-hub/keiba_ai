from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.predictor import Predictor


REAL_FEATURES_FAVORITE = {
    "favorite_rank": 1,
    "field_size": 14,
    "market_support": 0.42,
    "rank_score": 0.95,
    "recent_form_score": 0.5,
    "consistency_index": 0.5,
}
REAL_FEATURES_LONGSHOT = {
    "favorite_rank": 12,
    "field_size": 14,
    "market_support": 0.02,
    "rank_score": 0.1,
    "recent_form_score": 0.5,
    "consistency_index": 0.5,
}


def _mismatch_predictor() -> Predictor:
    """The bundled model was trained on placeholder names f0..f3, so real
    feature dicts share no keys with it — the historical silent-constant bug."""
    predictor = Predictor()
    if not predictor.trained:
        # simulate a trained model with alien feature names
        predictor.feature_names = ["f0", "f1", "f2", "f3"]
    assert not set(predictor.feature_names or []) & set(REAL_FEATURES_FAVORITE)
    return predictor


def test_predict_falls_back_when_no_model_feature_matches():
    predictor = _mismatch_predictor()
    if not predictor.trained:
        return  # guard is only reachable with a trained model artifact
    fav = predictor.predict("R1", "1", REAL_FEATURES_FAVORITE, odds=2.5)
    longshot = predictor.predict("R1", "2", REAL_FEATURES_LONGSHOT, odds=40.0)
    # a blind model must not return one constant for every horse; the
    # odds-anchored fallback must differentiate favorite from longshot
    assert fav != longshot
    assert fav > longshot


def test_predict_raw_falls_back_when_no_model_feature_matches():
    predictor = _mismatch_predictor()
    if not predictor.trained:
        return
    fav = predictor.predict_raw(REAL_FEATURES_FAVORITE, odds=2.5)
    longshot = predictor.predict_raw(REAL_FEATURES_LONGSHOT, odds=40.0)
    assert fav != longshot
    assert fav > longshot
