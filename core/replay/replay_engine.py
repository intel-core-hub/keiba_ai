"""
replay_engine.py

Engine to iterate recorded decisions, reconstruct historical state and run
validators/reconstructors to produce an audit report.
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from .historical_snapshot_loader import HistoricalSnapshotLoader
from .replay_validator import ReplayValidator
from .decision_reconstructor import DecisionReconstructor


class ReplayEngine:
    def __init__(
        self,
        loader: HistoricalSnapshotLoader,
        model_loader: Optional[callable] = None,
        validator: Optional[ReplayValidator] = None,
    ) -> None:
        self.loader = loader
        self.model_loader = model_loader
        self.validator = validator or ReplayValidator()
        self.reconstructor = DecisionReconstructor(model_loader) if model_loader else None

    def replay(self, decision_log_path: Path, out_report: Optional[Path] = None) -> Dict[str,Any]:
        p = Path(decision_log_path)
        if p.suffix.lower() != ".jsonl":
            raise ValueError("ReplayEngine accepts JSONL decision logs only")

        events = []
        records = []
        with p.open('r', encoding='utf-8') as fh:
            for line in fh:
                line=line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                events.append(event)
                event_type = event.get("event_type") or event.get("event")
                if event_type and event_type not in {"bet_executed", "BetSubmitted"}:
                    continue
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
                records.append({"event_type": event_type, "payload": payload})

        event_chain = self.validator.validate_event_chain(events)
        audit_evidence = self._audit_evidence_by_race(events)
        report = {
            "summary": {
                "total": len(records),
                "replay_mismatch_count": 0,
                "snapshot_after_decision": 0,
                "missing_hash": 0,
                "anomaly_count": 0,
                "riskclamp_bypass": event_chain["riskclamp_bypass"],
                "stale_data_bet": event_chain["stale_data_bet"],
                "missing_audit_hash": event_chain["missing_audit_hash"],
                "event_chain_mismatch": event_chain["chain_mismatch"],
            },
            "event_chain": event_chain,
            "items": [],
        }

        for record in records:
            rec = record["payload"]
            record_event_type = record.get("event_type")
            race_evidence = audit_evidence.get(str(rec.get("race_id") or ""), {})
            item = {"decision_id": rec.get('decision_id')}
            # parse timestamp
            ts = rec.get('timestamp', rec.get('decision_time_utc'))
            if isinstance(ts, str):
                try:
                    decision_ts = datetime.fromisoformat(ts)
                except Exception:
                    decision_ts = None
            else:
                decision_ts = ts

            # load snapshots
            odds = None
            features = None
            calibration = None
            try:
                if decision_ts:
                    odds = self.loader.get_latest_odds(decision_ts, race_id=rec.get('race_id'))
                    features = self.loader.get_latest_features(decision_ts, entity_id=rec.get('entity_id'))
                    calibration = self.loader.get_calibration_state(decision_ts)
            except Exception as e:
                item['load_error'] = str(e)

            # basic validations
            if hasattr(odds, 'empty') and not getattr(odds, 'empty'):
                odds_ts = odds[self.loader.timestamp_col].max()
            else:
                odds_ts = None
            if hasattr(features, 'empty') and not getattr(features, 'empty'):
                feature_ts = features[self.loader.timestamp_col].max()
            else:
                feature_ts = None

            item['validations'] = {}
            item['validations']['odds_snapshot_hash'] = self._require_hash(
                rec,
                ("odds_snapshot_hash", "odds_hash"),
                "missing_odds_snapshot",
            )
            item['validations']['feature_snapshot_hash'] = self._require_hash(
                rec,
                ("feature_snapshot_hash", "feature_hash"),
                "missing_feature_hash",
            )
            item['validations']['timestamp_consistency'] = self._validate_odds_snapshot(
                rec,
                decision_ts,
                odds_ts,
                race_evidence,
                audit_chain_record=record_event_type == "BetSubmitted",
            )
            item['validations']['feature_availability'] = self._validate_feature_snapshot(
                rec,
                decision_ts,
                feature_ts,
                race_evidence,
                audit_chain_record=record_event_type == "BetSubmitted",
            )
            item['validations']['model_version'] = self.validator.validate_model_version(
                rec.get('model_hash', rec.get('model_pkl_sha256', rec.get('model_version'))),
                rec.get('active_model_hash', rec.get('model_hash', rec.get('model_pkl_sha256', rec.get('model_version')))),
            )
            calib_ts = None
            if hasattr(calibration, 'empty') and not getattr(calibration, 'empty'):
                calib_ts = calibration[self.loader.timestamp_col].max()
            item['validations']['calibration'] = self._validate_calibration_snapshot(
                rec,
                decision_ts,
                calib_ts,
                audit_chain_record=record_event_type == "BetSubmitted",
            )
            item['validations']['calibration_hash'] = self.validator.validate_calibration_hash(
                rec.get('calibration_hash'),
                rec.get('active_calibration_hash', rec.get('calibration_hash')),
            )
            item['validations']['bankroll_hash'] = self.validator.validate_bankroll_hash(
                rec.get('bankroll_hash'),
                rec.get('active_bankroll_hash', rec.get('bankroll_hash')),
            )

            # attempt reconstruction
            if self.reconstructor:
                item['reconstruction'] = self.reconstructor.reconstruct(rec, features)

            self._accumulate_summary(report["summary"], item)
            report['items'].append(item)

        if out_report:
            with out_report.open('w', encoding='utf-8') as fh:
                json.dump(report, fh, default=str, indent=2, ensure_ascii=False)

        return report

    def _audit_evidence_by_race(self, events: list[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        evidence: Dict[str, Dict[str, Any]] = {}
        for event in events:
            event_type = event.get("event_type") or event.get("event")
            if event_type not in {"OddsSnapshotReceived", "FeatureSnapshotBuilt", "PredictionMade", "RiskClampEvaluated"}:
                continue
            race_id = str(event.get("race_id") or event.get("payload", {}).get("race_id") or "")
            if not race_id:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            race = evidence.setdefault(
                race_id,
                {
                    "odds_snapshot_hashes": set(),
                    "feature_snapshot_hashes": set(),
                    "events": {},
                },
            )
            if payload.get("odds_snapshot_hash"):
                race["odds_snapshot_hashes"].add(str(payload["odds_snapshot_hash"]))
            if payload.get("feature_snapshot_hash"):
                race["feature_snapshot_hashes"].add(str(payload["feature_snapshot_hash"]))
            race["events"][event_type] = {
                "payload": payload,
                "occurred_at_utc": event.get("occurred_at_utc"),
                "entry_hash": event.get("entry_hash"),
            }
        return evidence

    def _validate_odds_snapshot(
        self,
        rec: Dict[str, Any],
        decision_ts: datetime | None,
        odds_ts: Any,
        race_evidence: Dict[str, Any],
        *,
        audit_chain_record: bool,
    ) -> Dict[str, Any]:
        if odds_ts is not None:
            return self.validator.validate_timestamp_consistency(decision_ts, odds_ts)
        if audit_chain_record:
            odds_hashes = race_evidence.get("odds_snapshot_hashes", set())
            if rec.get("odds_snapshot_hash") and str(rec.get("odds_snapshot_hash")) in odds_hashes:
                return {"status": "pass", "source": "audit_event_chain"}
        return self.validator.validate_timestamp_consistency(decision_ts, odds_ts)

    def _validate_feature_snapshot(
        self,
        rec: Dict[str, Any],
        decision_ts: datetime | None,
        feature_ts: Any,
        race_evidence: Dict[str, Any],
        *,
        audit_chain_record: bool,
    ) -> Dict[str, Any]:
        if feature_ts is not None:
            return self.validator.validate_feature_availability(decision_ts, feature_ts)
        if audit_chain_record:
            feature_hashes = race_evidence.get("feature_snapshot_hashes", set())
            if rec.get("feature_snapshot_hash") and str(rec.get("feature_snapshot_hash")) in feature_hashes:
                return {"status": "pass", "source": "audit_event_chain"}
        return self.validator.validate_feature_availability(decision_ts, feature_ts)

    def _validate_calibration_snapshot(
        self,
        rec: Dict[str, Any],
        decision_ts: datetime | None,
        calibration_ts: Any,
        *,
        audit_chain_record: bool,
    ) -> Dict[str, Any]:
        if calibration_ts is not None:
            return self.validator.validate_calibration_timing(decision_ts, calibration_ts)
        if audit_chain_record and rec.get("calibration_hash"):
            return {"status": "pass", "source": "submitted_payload"}
        return self.validator.validate_calibration_timing(decision_ts, calibration_ts)

    def _require_hash(
        self,
        rec: Dict[str, Any],
        keys: tuple[str, ...],
        reason: str,
    ) -> Dict[str, Any]:
        if any(rec.get(key) for key in keys):
            return {"status": "pass"}
        return {"status": "fail", "reason": reason}

    def _accumulate_summary(self, summary: Dict[str, Any], item: Dict[str, Any]) -> None:
        for validation in item.get("validations", {}).values():
            if not isinstance(validation, dict) or validation.get("status") != "fail":
                continue
            reason = validation.get("reason")
            summary["anomaly_count"] += 1
            if reason == "snapshot_after_decision":
                summary["snapshot_after_decision"] += 1
            elif reason in {"missing_feature_hash", "missing_odds_snapshot"}:
                summary["missing_hash"] += 1
            else:
                summary["replay_mismatch_count"] += 1

    def raise_on_failures(self, report: Dict[str, Any]) -> None:
        summary = report.get("summary", {})
        if (
            int(summary.get("replay_mismatch_count", 0)) > 0
            or int(summary.get("snapshot_after_decision", 0)) > 0
            or int(summary.get("missing_hash", 0)) > 0
            or int(summary.get("riskclamp_bypass", 0)) > 0
            or int(summary.get("stale_data_bet", 0)) > 0
            or int(summary.get("missing_audit_hash", 0)) > 0
            or int(summary.get("event_chain_mismatch", 0)) > 0
        ):
            raise RuntimeError(f"Replay gate failed: {summary}")
