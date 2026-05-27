"""
decision_reconstructor.py

Given a recorded decision and the snapshot state available at that time,
attempt to deterministically reconstruct the decision by invoking the
corresponding model (if available) and comparing outputs.

This module provides a small adapter pattern: a `model_loader` callable that
accepts a `version` and returns an object with `predict_proba(X)`.
"""
from __future__ import annotations
from typing import Any, Dict, Callable
import pandas as pd


class DecisionReconstructor:
    def __init__(self, model_loader: Callable[[str], Any]):
        self.model_loader = model_loader

    def reconstruct(self, decision_record: Dict[str,Any], feature_snapshot: pd.DataFrame) -> Dict[str,Any]:
        """Attempt to reconstruct decision. Returns dictionary with status and details.

        Expects decision_record to contain keys: `model_version`, `timestamp`, `decision_proba` (optional)
        feature_snapshot is a single-row DataFrame (or compatible) with model inputs.
        """
        version = decision_record.get('model_version')
        if version is None:
            return {"status":"fail","reason":"missing_model_version"}
        model = None
        try:
            model = self.model_loader(version)
        except Exception as e:
            return {"status":"fail","reason":"model_load_error","error":str(e)}

        if model is None:
            return {"status":"fail","reason":"model_not_available","version":version}

        # prepare features: assume feature_snapshot is a single-row DataFrame
        if feature_snapshot is None or feature_snapshot.empty:
            return {"status":"fail","reason":"missing_features"}

        try:
            X = feature_snapshot.drop(columns=[c for c in ['timestamp','entity_id','race_id'] if c in feature_snapshot.columns], errors='ignore')
            # keep first row
            X = X.iloc[[0]]
            proba = None
            if hasattr(model, 'predict_proba'):
                proba = model.predict_proba(X)
            elif hasattr(model, 'predict'):
                proba = model.predict(X)
            else:
                return {"status":"fail","reason":"model_has_no_predict"}
            return {"status":"ok","model_version":version,"reconstructed_proba":proba.tolist() if hasattr(proba,'tolist') else proba}
        except Exception as e:
            return {"status":"fail","reason":"reconstruction_error","error":str(e)}
