from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


EVENT_TYPES = {
    "OddsSnapshotReceived",
    "FeatureSnapshotBuilt",
    "PredictionMade",
    "RiskClampEvaluated",
    "BetSubmitted",
    "BetTypeExecutionRejected",
    "BetAccepted",
    "BetRejected",
    "RaceSettled",
    "BankrollUpdated",
}


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    event_type: str
    occurred_at_utc: str
    race_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    previous_hash: str | None = None
    entry_hash: str | None = None

    def validate(self) -> "AuditEvent":
        if not self.event_id:
            raise ValueError("event_id is required")
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"invalid event_type: {self.event_type}")
        if not self.race_id:
            raise ValueError("race_id is required")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a dictionary")
        _parse_utc(self.occurred_at_utc)
        if self.entry_hash and self.entry_hash != self.canonical_hash():
            raise ValueError("entry_hash mismatch")
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())


def canonical_hash(payload: dict[str, Any]) -> str:
    record = {key: payload[key] for key in sorted(payload) if key != "entry_hash"}
    serialized = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_audit_event(
    *,
    event_id: str,
    event_type: str,
    occurred_at_utc: str,
    race_id: str,
    payload: dict[str, Any] | None = None,
    previous_hash: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at_utc=occurred_at_utc,
        race_id=race_id,
        payload=payload or {},
        previous_hash=previous_hash,
    )
    return AuditEvent(**{**event.to_dict(), "entry_hash": event.canonical_hash()}).validate()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("occurred_at_utc must include timezone")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("occurred_at_utc must be UTC")
    return parsed
