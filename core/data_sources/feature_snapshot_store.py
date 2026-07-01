from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.data_sources.local_file_provider import canonical_hash, parse_utc_datetime


BANNED_FEATURE_KEYS = {
    "result",
    "payout",
    "win_payout",
    "finish_position",
    "is_win",
    "confirmed_result",
    "settled_profit",
    "post_race",
    "final_odds_after_race",
}


class FeatureSnapshotStore:
    def __init__(self, root: Path = Path("data/feature_snapshots")) -> None:
        self.root = root

    def save(
        self,
        *,
        race_id: str,
        horse_id: str,
        features: dict[str, Any],
        source_cutoff_time_utc: datetime | str,
        feature_version: str = "v1",
        snapshot_time_utc: datetime | str | None = None,
    ) -> str:
        if not race_id or not horse_id:
            raise ValueError("race_id and horse_id are required")
        if not isinstance(features, dict):
            raise TypeError("features must be a dict")
        self._reject_contamination(features)
        cutoff = _coerce_utc(source_cutoff_time_utc, "source_cutoff_time_utc")
        snapshot_time = _coerce_utc(snapshot_time_utc, "snapshot_time_utc") if snapshot_time_utc else datetime.now(timezone.utc)
        payload = {
            "race_id": race_id,
            "horse_id": horse_id,
            "snapshot_time_utc": snapshot_time.isoformat(),
            "source_cutoff_time_utc": cutoff.isoformat(),
            "feature_version": feature_version,
            "features": features,
        }
        feature_hash = canonical_hash(payload)
        row = {**payload, "feature_snapshot_hash": feature_hash}
        outdir = self.root / snapshot_time.date().isoformat()
        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / f"{race_id}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        return feature_hash

    def _reject_contamination(self, value: Any, *, path: str = "") -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).strip().lower()
                if normalized in BANNED_FEATURE_KEYS:
                    where = f"{path}.{key}" if path else str(key)
                    raise ValueError(f"forbidden post-race feature key: {where}")
                self._reject_contamination(nested, path=f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for idx, nested in enumerate(value):
                self._reject_contamination(nested, path=f"{path}[{idx}]")


def _coerce_utc(value: datetime | str, field: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"{field} must include timezone")
        return value.astimezone(timezone.utc)
    return parse_utc_datetime(value, field=field)
