"""Replay validators for production gate hard-fail semantics."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable


class ReplayValidator:
    def __init__(self, allow_skew_seconds: int = 0) -> None:
        self.allow_skew_seconds = allow_skew_seconds

    def validate_timestamp_consistency(
        self,
        decision_ts: datetime | None,
        odds_ts: datetime | None,
    ) -> Dict[str, Any]:
        if odds_ts is None:
            return {"status": "fail", "reason": "missing_odds_snapshot"}
        if decision_ts is None:
            return {"status": "fail", "reason": "non_deterministic_replay_result"}
        if odds_ts > decision_ts and (odds_ts - decision_ts).total_seconds() > self.allow_skew_seconds:
            return {
                "status": "fail",
                "reason": "snapshot_after_decision",
                "odds_ts": odds_ts.isoformat(),
                "decision_ts": decision_ts.isoformat(),
            }
        return {"status": "pass"}

    def validate_feature_availability(
        self,
        decision_ts: datetime | None,
        feature_ts: datetime | None,
    ) -> Dict[str, Any]:
        if feature_ts is None:
            return {"status": "fail", "reason": "missing_feature_hash"}
        if decision_ts is None:
            return {"status": "fail", "reason": "non_deterministic_replay_result"}
        if feature_ts > decision_ts and (feature_ts - decision_ts).total_seconds() > self.allow_skew_seconds:
            return {
                "status": "fail",
                "reason": "snapshot_after_decision",
                "feature_ts": feature_ts.isoformat(),
                "decision_ts": decision_ts.isoformat(),
            }
        return {"status": "pass"}

    def validate_model_version(self, recorded_version: str | None, active_version: str | None) -> Dict[str, Any]:
        if not recorded_version or not active_version or recorded_version != active_version:
            return {
                "status": "fail",
                "reason": "model_hash_mismatch",
                "recorded": recorded_version,
                "active": active_version,
            }
        return {"status": "pass"}

    def validate_calibration_hash(
        self,
        recorded_hash: str | None,
        active_hash: str | None,
    ) -> Dict[str, Any]:
        if not recorded_hash or not active_hash or recorded_hash != active_hash:
            return {
                "status": "fail",
                "reason": "calibration_hash_mismatch",
                "recorded": recorded_hash,
                "active": active_hash,
            }
        return {"status": "pass"}

    def validate_bankroll_hash(
        self,
        recorded_hash: str | None,
        active_hash: str | None,
    ) -> Dict[str, Any]:
        if not recorded_hash or not active_hash or recorded_hash != active_hash:
            return {
                "status": "fail",
                "reason": "bankroll_state_mismatch",
                "recorded": recorded_hash,
                "active": active_hash,
            }
        return {"status": "pass"}

    def validate_calibration_timing(
        self,
        decision_ts: datetime | None,
        calibration_ts: datetime | None,
    ) -> Dict[str, Any]:
        if calibration_ts is None:
            return {"status": "fail", "reason": "calibration_hash_mismatch"}
        if decision_ts is None:
            return {"status": "fail", "reason": "non_deterministic_replay_result"}
        if calibration_ts > decision_ts:
            return {
                "status": "fail",
                "reason": "snapshot_after_decision",
                "calibration_ts": calibration_ts.isoformat(),
                "decision_ts": decision_ts.isoformat(),
            }
        return {"status": "pass"}

    def validate_event_chain(self, events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        summary = {
            "bet_submitted": 0,
            "riskclamp_bypass": 0,
            "stale_data_bet": 0,
            "missing_audit_hash": 0,
            "chain_mismatch": 0,
            "items": [],
        }
        seen_by_race: dict[str, set[str]] = {}
        risk_proof_by_race: dict[str, Dict[str, Any]] = {}
        previous_hash: str | None = None

        for event in events:
            event_type = event.get("event_type") or event.get("event")
            race_id = str(event.get("race_id") or event.get("payload", {}).get("race_id") or "")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}

            if event_type in {
                "OddsSnapshotReceived",
                "FeatureSnapshotBuilt",
                "PredictionMade",
                "RiskClampEvaluated",
                "BetSubmitted",
                "BetAccepted",
                "BetRejected",
                "RaceSettled",
                "BankrollUpdated",
            }:
                if not event.get("entry_hash"):
                    summary["missing_audit_hash"] += 1
                    summary["items"].append({"event_id": event.get("event_id"), "reason": "missing_entry_hash"})
                if event.get("previous_hash") != previous_hash:
                    summary["chain_mismatch"] += 1
                    summary["items"].append({"event_id": event.get("event_id"), "reason": "previous_hash_mismatch"})
                previous_hash = event.get("entry_hash")

            if not race_id:
                continue

            seen = seen_by_race.setdefault(race_id, set())
            if event_type == "RiskClampEvaluated":
                risk_proof_by_race[race_id] = payload
            elif event_type == "BetSubmitted":
                summary["bet_submitted"] += 1
                required_prior = {"OddsSnapshotReceived", "FeatureSnapshotBuilt", "PredictionMade"}
                proof = risk_proof_by_race.get(race_id, {})
                if not required_prior.issubset(seen) or not proof.get("allowed") or not proof.get("risk_limits_hash"):
                    summary["riskclamp_bypass"] += 1
                    summary["items"].append({"event_id": event.get("event_id"), "reason": "riskclamp_bypass"})
                if proof.get("stale_data") or payload.get("stale_data") or payload.get("stale_snapshot"):
                    summary["stale_data_bet"] += 1
                    summary["items"].append({"event_id": event.get("event_id"), "reason": "stale_data_bet"})

            if event_type:
                seen.add(str(event_type))

        summary["valid"] = (
            summary["riskclamp_bypass"] == 0
            and summary["stale_data_bet"] == 0
            and summary["missing_audit_hash"] == 0
            and summary["chain_mismatch"] == 0
        )
        return summary
