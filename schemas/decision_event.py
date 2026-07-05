from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

VALID_DECISIONS = {"BET", "NO_BET"}
REQUIRED_HASH_FIELDS = (
    "odds_snapshot_hash",
    "feature_snapshot_hash",
    "model_hash",
    "calibration_hash",
    "bankroll_hash",
    "policy_hash",
    "risk_limits_hash",
)


@dataclass(frozen=True)
class DecisionEvent:
    decision_id: str
    race_id: str
    selection_id: str
    decision_time_utc: str
    monotonic_ns: int
    odds_snapshot_hash: str
    feature_snapshot_hash: str
    model_hash: str
    calibration_hash: str
    bankroll_hash: str
    policy_hash: str
    risk_limits_hash: str
    decision: str
    reason: str
    stake: float
    execution_status: str

    def validate(self) -> "DecisionEvent":
        for field_name, value in self.to_dict().items():
            if field_name == "stake":
                continue
            if value is None or value == "":
                raise ValueError(f"{field_name} is required")

        for field_name in REQUIRED_HASH_FIELDS:
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} hash is required")

        if self.decision not in VALID_DECISIONS:
            raise ValueError(f"invalid decision: {self.decision}")
        if self.stake < 0:
            raise ValueError("stake must be non-negative")
        if self.monotonic_ns < 0:
            raise ValueError("monotonic_ns must be non-negative")
        _parse_utc(self.decision_time_utc)
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_hash(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _parse_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("decision_time_utc must include timezone")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("decision_time_utc must be UTC")
    return parsed
