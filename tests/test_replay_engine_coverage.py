from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.replay.replay_engine import ReplayEngine


class _Loader:
    timestamp_col = "timestamp"

    def __init__(self, *, odds=None, features=None, calibration=None, raise_error: bool = False):
        self.odds = odds
        self.features = features
        self.calibration = calibration
        self.raise_error = raise_error

    def get_latest_odds(self, as_of, race_id=None):
        if self.raise_error:
            raise RuntimeError("loader failed")
        return self.odds

    def get_latest_features(self, as_of, entity_id=None):
        if self.raise_error:
            raise RuntimeError("loader failed")
        return self.features

    def get_calibration_state(self, as_of):
        if self.raise_error:
            raise RuntimeError("loader failed")
        return self.calibration


class _Model:
    def predict(self, frame):
        return pd.Series([0.42])


def _frame(ts: datetime | None, **cols) -> pd.DataFrame:
    if ts is None:
        return pd.DataFrame()
    return pd.DataFrame([{"timestamp": ts, **cols}])


def _submitted_payload(ts: str, **overrides) -> dict[str, object]:
    payload = {
        "decision_id": "D1",
        "race_id": "R1",
        "selection": "H1",
        "selection_id": "H1",
        "entity_id": "E1",
        "timestamp": ts,
        "decision_time_utc": ts,
        "model_hash": "model-hash",
        "active_model_hash": "model-hash",
        "model_version": "model-v1",
        "calibration_hash": "calibration-hash",
        "active_calibration_hash": "calibration-hash",
        "bankroll_hash": "bankroll-hash",
        "active_bankroll_hash": "bankroll-hash",
        "odds_snapshot_hash": "odds-hash",
        "feature_snapshot_hash": "feature-hash",
    }
    payload.update(overrides)
    return payload


def _chain_events(ts: str, *, payload: dict[str, object] | None = None) -> list[dict[str, object]]:
    payload = payload or _submitted_payload(ts)
    return [
        {
            "event_id": "E1",
            "event_type": "OddsSnapshotReceived",
            "occurred_at_utc": ts,
            "race_id": "R1",
            "payload": {"odds_snapshot_hash": "odds-hash", "race_id": "R1"},
            "previous_hash": None,
            "entry_hash": "hash-1",
        },
        {
            "event_id": "E2",
            "event_type": "FeatureSnapshotBuilt",
            "occurred_at_utc": ts,
            "race_id": "R1",
            "payload": {"feature_snapshot_hash": "feature-hash", "race_id": "R1"},
            "previous_hash": "hash-1",
            "entry_hash": "hash-2",
        },
        {
            "event_id": "E3",
            "event_type": "PredictionMade",
            "occurred_at_utc": ts,
            "race_id": "R1",
            "payload": {"model_hash": "model-hash", "race_id": "R1"},
            "previous_hash": "hash-2",
            "entry_hash": "hash-3",
        },
        {
            "event_id": "E4",
            "event_type": "RiskClampEvaluated",
            "occurred_at_utc": ts,
            "race_id": "R1",
            "payload": {"allowed": True, "risk_limits_hash": "risk-hash", "race_id": "R1"},
            "previous_hash": "hash-3",
            "entry_hash": "hash-4",
        },
        {
            "event_id": "E5",
            "event_type": "BetSubmitted",
            "occurred_at_utc": ts,
            "race_id": "R1",
            "payload": payload,
            "previous_hash": "hash-4",
            "entry_hash": "hash-5",
        },
    ]


def test_replay_engine_helper_branches_cover_audit_fallbacks():
    engine = ReplayEngine(loader=_Loader())
    decision_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    race_evidence = {
        "odds_snapshot_hashes": {"odds-hash"},
        "feature_snapshot_hashes": {"feature-hash"},
    }

    assert engine._validate_odds_snapshot(
        {"odds_snapshot_hash": "odds-hash"},
        decision_ts,
        None,
        race_evidence,
        audit_chain_record=True,
    ) == {"status": "pass", "source": "audit_event_chain"}
    assert engine._validate_feature_snapshot(
        {"feature_snapshot_hash": "feature-hash"},
        decision_ts,
        None,
        race_evidence,
        audit_chain_record=True,
    ) == {"status": "pass", "source": "audit_event_chain"}
    assert engine._validate_calibration_snapshot(
        {"calibration_hash": "calibration-hash"},
        decision_ts,
        None,
        audit_chain_record=True,
    ) == {"status": "pass", "source": "submitted_payload"}
    assert engine._require_hash({"odds_hash": "x"}, ("odds_snapshot_hash", "odds_hash"), "missing") == {"status": "pass"}
    assert engine._require_hash({}, ("odds_snapshot_hash", "odds_hash"), "missing") == {"status": "fail", "reason": "missing"}

    evidence = engine._audit_evidence_by_race(_chain_events("2026-01-01T00:00:00+00:00"))
    assert evidence["R1"]["odds_snapshot_hashes"] == {"odds-hash"}
    assert evidence["R1"]["feature_snapshot_hashes"] == {"feature-hash"}

    summary = {
        "replay_mismatch_count": 0,
        "snapshot_after_decision": 0,
        "missing_hash": 0,
        "anomaly_count": 0,
    }
    engine._accumulate_summary(
        summary,
        {
            "validations": {
                "t1": {"status": "fail", "reason": "snapshot_after_decision"},
                "t2": {"status": "fail", "reason": "missing_feature_hash"},
                "t3": {"status": "fail", "reason": "model_hash_mismatch"},
                "ok": {"status": "pass"},
            }
        },
    )
    assert summary == {
        "replay_mismatch_count": 1,
        "snapshot_after_decision": 1,
        "missing_hash": 1,
        "anomaly_count": 3,
    }

    engine.raise_on_failures({"summary": {"replay_mismatch_count": 0, "snapshot_after_decision": 0, "missing_hash": 0, "riskclamp_bypass": 0, "stale_data_bet": 0, "missing_audit_hash": 0, "event_chain_mismatch": 0}})
    with pytest.raises(RuntimeError):
        engine.raise_on_failures({"summary": {"replay_mismatch_count": 1}})


def test_replay_engine_replay_uses_audit_chain_fallback_and_writes_report(tmp_path):
    ts = "2026-01-01T00:00:00+00:00"
    path = tmp_path / "decisions.jsonl"
    report_path = tmp_path / "replay_report.json"
    lines = ["not-json", json.dumps({"event_type": "IgnoredEvent", "payload": {"race_id": "R0"}})]
    lines.extend(json.dumps(event, ensure_ascii=False) for event in _chain_events(ts))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    engine = ReplayEngine(
        loader=_Loader(
            odds=pd.DataFrame(),
            features=pd.DataFrame(),
            calibration=pd.DataFrame(),
        ),
        model_loader=lambda version: _Model(),
    )
    report = engine.replay(path, out_report=report_path)

    assert report_path.exists()
    assert report["summary"]["total"] == 1
    assert report["summary"]["anomaly_count"] == 0
    item = report["items"][0]
    assert item["validations"]["timestamp_consistency"]["source"] == "audit_event_chain"
    assert item["validations"]["feature_availability"]["source"] == "audit_event_chain"
    assert item["validations"]["calibration"]["source"] == "submitted_payload"
    assert item["reconstruction"]["status"] == "fail"
    assert item["reconstruction"]["reason"] == "missing_features"


def test_replay_engine_replay_collects_load_errors_and_mismatches(tmp_path):
    path = tmp_path / "decisions.jsonl"
    record = {
        "event": "bet_executed",
        "decision_id": "D2",
        "race_id": "R2",
        "selection": "H2",
        "timestamp": 123,
        "model_hash": "recorded-model",
        "active_model_hash": "active-model",
        "calibration_hash": "recorded-calibration",
        "active_calibration_hash": "active-calibration",
        "bankroll_hash": "recorded-bankroll",
        "active_bankroll_hash": "active-bankroll",
        "odds_snapshot_hash": "",
        "feature_snapshot_hash": "",
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    engine = ReplayEngine(loader=_Loader(raise_error=True))
    report = engine.replay(path)

    assert report["summary"]["total"] == 1
    assert report["summary"]["missing_hash"] >= 1
    assert report["summary"]["replay_mismatch_count"] >= 1
    assert "load_error" in report["items"][0]
    with pytest.raises(RuntimeError):
        engine.raise_on_failures(report)


def test_replay_engine_reconstructs_when_features_and_model_are_present(tmp_path):
    decision_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    payload = _submitted_payload(
        decision_ts.isoformat(),
        model_version="model-v2",
        active_model_hash="model-hash",
    )
    event = {
        "event_type": "BetSubmitted",
        "race_id": "R1",
        "payload": payload,
        "previous_hash": None,
        "entry_hash": "hash-1",
    }
    path = tmp_path / "decisions.jsonl"
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")

    engine = ReplayEngine(
        loader=_Loader(
            odds=_frame(decision_ts - timedelta(seconds=1), race_id="R1", runner_id="H1"),
            features=_frame(decision_ts - timedelta(seconds=1), entity_id="E1", race_id="R1", speed=1.0),
            calibration=_frame(decision_ts - timedelta(seconds=1), state="ok"),
        ),
        model_loader=lambda version: _Model(),
    )
    report = engine.replay(path)

    assert report["items"][0]["reconstruction"]["status"] == "ok"
    assert report["items"][0]["reconstruction"]["reconstructed_proba"] == [0.42]
