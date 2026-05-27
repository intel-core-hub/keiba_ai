"""Odds snapshot primitives for leakage-safe market timing.

This module keeps the market view explicit:
- available-at-bet-time odds
- final closing odds
- post-market information

The code is intentionally conservative. Plain ``odds`` columns are treated as
ambiguous unless the caller explicitly maps them to a snapshot label.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Mapping

import pandas as pd


SNAPSHOT_LABELS: tuple[str, ...] = ("t-60min", "t-30min", "t-10min", "final odds")
PRE_RACE_LABELS: tuple[str, ...] = ("t-60min", "t-30min", "t-10min")
CLOSING_LABELS: tuple[str, ...] = ("final odds",)

SNAPSHOT_OFFSETS: dict[str, timedelta] = {
    "t-60min": timedelta(minutes=60),
    "t-30min": timedelta(minutes=30),
    "t-10min": timedelta(minutes=10),
    "final odds": timedelta(minutes=0),
}

SNAPSHOT_ALIASES: dict[str, tuple[str, ...]] = {
    "t-60min": ("odds_t60", "odds_60m", "odds_60min", "favorite_rank_t60", "favorite_t60"),
    "t-30min": ("odds_t30", "odds_30m", "odds_30min", "favorite_rank_t30", "favorite_t30"),
    "t-10min": ("odds_t10", "odds_10m", "odds_10min", "favorite_rank_t10", "favorite_t10"),
    "final odds": ("final_odds", "closing_odds", "closing_price", "market_odds"),
}


def normalize_snapshot_label(label: str | None) -> str:
    if label is None:
        return "unknown"
    lower = str(label).strip().lower().replace("_", " ")
    if lower in {"final", "closing", "final odds", "closing odds"}:
        return "final odds"
    if lower in {"t-60", "t60", "60m", "60 min", "60min"}:
        return "t-60min"
    if lower in {"t-30", "t30", "30m", "30 min", "30min"}:
        return "t-30min"
    if lower in {"t-10", "t10", "10m", "10 min", "10min"}:
        return "t-10min"
    return str(label).strip().lower()


def parse_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    try:
        ts = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except Exception:
        return None
    if pd.isna(num):
        return None
    return float(num)


def infer_snapshot_label(column_name: str) -> str | None:
    lower = column_name.lower()
    for label, aliases in SNAPSHOT_ALIASES.items():
        if any(alias in lower for alias in aliases):
            return label
    if lower in {"odds", "favorite_rank", "favorite"}:
        return "ambiguous"
    return None


@dataclass(frozen=True)
class OddsSnapshot:
    """Canonical market snapshot with explicit timing."""

    race_id: str
    horse_name: str | None
    snapshot_label: str
    odds: float | None = None
    favorite_rank: float | None = None
    available_at: pd.Timestamp | None = None
    race_start_at: pd.Timestamp | None = None
    captured_at: pd.Timestamp | None = None
    source: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def normalized_label(self) -> str:
        return normalize_snapshot_label(self.snapshot_label)

    @property
    def is_pre_race(self) -> bool:
        return self.normalized_label in PRE_RACE_LABELS

    @property
    def is_closing(self) -> bool:
        return self.normalized_label in CLOSING_LABELS

    @property
    def is_post_market(self) -> bool:
        return not self.is_pre_race and not self.is_closing

    @property
    def available_at_bet_time(self) -> bool:
        if self.available_at is None:
            return False
        if self.race_start_at is None:
            return True
        return self.available_at <= self.race_start_at

    def to_record(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "race_id": self.race_id,
            "horse_name": self.horse_name,
            "snapshot_label": normalize_snapshot_label(self.snapshot_label),
            "odds": self.odds,
            "favorite_rank": self.favorite_rank,
            "available_at": self.available_at.isoformat() if self.available_at is not None else None,
            "race_start_at": self.race_start_at.isoformat() if self.race_start_at is not None else None,
            "captured_at": self.captured_at.isoformat() if self.captured_at is not None else None,
            "source": self.source,
            "available_at_bet_time": self.available_at_bet_time,
            "is_pre_race": self.is_pre_race,
            "is_closing": self.is_closing,
            "is_post_market": self.is_post_market,
        }
        payload.update(dict(self.extra))
        return payload


def build_snapshot_record(
    row: Mapping[str, Any],
    snapshot_label: str,
    *,
    race_id_col: str = "race_id",
    horse_name_col: str = "horse_name",
    odds_col: str = "odds",
    favorite_rank_col: str = "favorite_rank",
    available_at_col: str | None = None,
    race_start_col: str | None = None,
    captured_at_col: str | None = None,
    source_col: str | None = None,
    extra_cols: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Create a canonical snapshot dictionary from a wide row."""

    race_id = row.get(race_id_col)
    horse_name = row.get(horse_name_col)
    odds = coerce_float(row.get(odds_col)) if odds_col in row else None
    favorite_rank = coerce_float(row.get(favorite_rank_col)) if favorite_rank_col in row else None
    available_at = parse_timestamp(row.get(available_at_col)) if available_at_col and available_at_col in row else None
    race_start_at = parse_timestamp(row.get(race_start_col)) if race_start_col and race_start_col in row else None
    captured_at = parse_timestamp(row.get(captured_at_col)) if captured_at_col and captured_at_col in row else None
    source = row.get(source_col) if source_col and source_col in row else None

    extra: dict[str, Any] = {}
    for col in extra_cols:
        if col in row:
            extra[col] = row.get(col)

    snapshot = OddsSnapshot(
        race_id=str(race_id) if race_id is not None else "",
        horse_name=str(horse_name) if horse_name is not None else None,
        snapshot_label=snapshot_label,
        odds=odds,
        favorite_rank=favorite_rank,
        available_at=available_at,
        race_start_at=race_start_at,
        captured_at=captured_at,
        source=str(source) if source is not None else None,
        extra=extra,
    )
    return snapshot.to_record()


def snapshot_available_columns(df: pd.DataFrame) -> dict[str, list[str]]:
    """Return candidate columns grouped by snapshot label."""

    candidates: dict[str, list[str]] = {label: [] for label in SNAPSHOT_LABELS}
    for column in df.columns:
        label = infer_snapshot_label(column)
        if label in candidates:
            candidates[label].append(column)
    return candidates