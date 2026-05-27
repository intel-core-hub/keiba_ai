"""
replay_validator.py

Validators that check timestamp consistency, model/calibration timing, and
feature/odds availability for a reconstructed decision state.
"""
from __future__ import annotations
from datetime import datetime
from typing import Dict, Any


class ReplayValidator:
    def __init__(self, allow_skew_seconds: int = 0) -> None:
        # allow a small clock skew tolerance when comparing timestamps
        self.allow_skew_seconds = allow_skew_seconds

    def validate_timestamp_consistency(self, decision_ts: datetime, odds_ts: datetime) -> Dict[str,Any]:
        if odds_ts is None:
            return {"status":"fail","reason":"missing_odds_timestamp"}
        if odds_ts > decision_ts and (odds_ts - decision_ts).total_seconds() > self.allow_skew_seconds:
            return {"status":"fail","reason":"odds_after_decision","odds_ts":odds_ts.isoformat(),"decision_ts":decision_ts.isoformat()}
        return {"status":"pass"}

    def validate_feature_availability(self, decision_ts: datetime, feature_ts: datetime) -> Dict[str,Any]:
        if feature_ts is None:
            return {"status":"fail","reason":"missing_feature_timestamp"}
        if feature_ts > decision_ts and (feature_ts - decision_ts).total_seconds() > self.allow_skew_seconds:
            return {"status":"fail","reason":"feature_after_decision","feature_ts":feature_ts.isoformat(),"decision_ts":decision_ts.isoformat()}
        return {"status":"pass"}

    def validate_model_version(self, recorded_version: str, active_version: str) -> Dict[str,Any]:
        if recorded_version != active_version:
            return {"status":"warn","reason":"model_version_mismatch","recorded":recorded_version,"active":active_version}
        return {"status":"pass"}

    def validate_calibration_timing(self, decision_ts: datetime, calibration_ts: datetime) -> Dict[str,Any]:
        if calibration_ts is None:
            return {"status":"warn","reason":"missing_calibration_state"}
        if calibration_ts > decision_ts:
            return {"status":"fail","reason":"calibration_after_decision","calibration_ts":calibration_ts.isoformat()}
        return {"status":"pass"}
