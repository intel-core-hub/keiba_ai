"""Helpers for splitting market history into explicit timestamped snapshots."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Iterable

try:
    import pandas as pd
except Exception:
    pd = None

from .odds_snapshot import (
    CLOSING_LABELS,
    PRE_RACE_LABELS,
    SNAPSHOT_LABELS,
    SNAPSHOT_OFFSETS,
    build_snapshot_record,
    normalize_snapshot_label,
    parse_timestamp,
    snapshot_available_columns,
)


@dataclass
class SnapshotConfig:
    race_id_col: str = "race_id"
    horse_name_col: str = "horse_name"
    race_start_col: str | None = None
    bet_time_col: str | None = None
    captured_at_col: str | None = None
    source_col: str | None = None
    odds_col: str = "odds"
    favorite_rank_col: str = "favorite_rank"
    plain_odds_snapshot_label: str | None = None
    strict: bool = True


class OddsHistoryManager:
    """Convert wide market data into leakage-safe long snapshots."""

    def __init__(self, config: SnapshotConfig | None = None):
        self.config = config or SnapshotConfig()
        self._frames: "OrderedDict[str, pd.DataFrame]" = OrderedDict()
        self._long_frame = pd.DataFrame()

    @staticmethod
    def _time_offset(label: str) -> timedelta | None:
        return SNAPSHOT_OFFSETS.get(normalize_snapshot_label(label))

    def load(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize a wide dataframe into a long snapshot frame."""

        records: list[dict[str, Any]] = []
        candidates = snapshot_available_columns(df)

        for _, row in df.iterrows():
            row_dict = row.to_dict()
            race_id = row_dict.get(self.config.race_id_col)
            race_start_at = parse_timestamp(row_dict.get(self.config.race_start_col)) if self.config.race_start_col else None
            bet_time = parse_timestamp(row_dict.get(self.config.bet_time_col)) if self.config.bet_time_col else None
            captured_at = parse_timestamp(row_dict.get(self.config.captured_at_col)) if self.config.captured_at_col else None

            for label in SNAPSHOT_LABELS:
                odds_columns = [c for c in candidates.get(label, []) if c.lower().startswith("odds") or c.lower() in {"final_odds", "closing_odds", "market_odds"}]
                rank_columns = [c for c in candidates.get(label, []) if c.lower().startswith("favorite")]
                if not odds_columns and not rank_columns:
                    continue

                odds_col = odds_columns[0] if odds_columns else self.config.odds_col
                rank_col = rank_columns[0] if rank_columns else self.config.favorite_rank_col
                available_at = self._infer_available_at(label, row_dict, race_start_at, bet_time)

                record = build_snapshot_record(
                    row_dict,
                    label,
                    race_id_col=self.config.race_id_col,
                    horse_name_col=self.config.horse_name_col,
                    odds_col=odds_col,
                    favorite_rank_col=rank_col,
                    race_start_col=self.config.race_start_col,
                    captured_at_col=self.config.captured_at_col,
                    source_col=self.config.source_col,
                )
                record["available_at"] = available_at.isoformat() if available_at is not None else record.get("available_at")
                record["bet_time"] = bet_time.isoformat() if bet_time is not None else None
                record["race_start_at"] = race_start_at.isoformat() if race_start_at is not None else record.get("race_start_at")
                record["snapshot_label"] = normalize_snapshot_label(label)
                record["snapshot_source_column"] = odds_col if odds_col in row_dict else rank_col
                record["plain_odds_role"] = None
                record["plain_odds_ambiguous"] = False
                records.append(record)

            if self.config.plain_odds_snapshot_label is not None and self.config.odds_col in row_dict:
                label = normalize_snapshot_label(self.config.plain_odds_snapshot_label)
                available_at = self._infer_available_at(label, row_dict, race_start_at, bet_time)
                record = build_snapshot_record(
                    row_dict,
                    label,
                    race_id_col=self.config.race_id_col,
                    horse_name_col=self.config.horse_name_col,
                    odds_col=self.config.odds_col,
                    favorite_rank_col=self.config.favorite_rank_col,
                    race_start_col=self.config.race_start_col,
                    captured_at_col=self.config.captured_at_col,
                    source_col=self.config.source_col,
                )
                record["available_at"] = available_at.isoformat() if available_at is not None else record.get("available_at")
                record["bet_time"] = bet_time.isoformat() if bet_time is not None else None
                record["race_start_at"] = race_start_at.isoformat() if race_start_at is not None else record.get("race_start_at")
                record["snapshot_label"] = label
                record["plain_odds_role"] = label
                record["plain_odds_ambiguous"] = False
                records.append(record)
            elif self.config.strict and self.config.odds_col in row_dict:
                records.append(
                    {
                        self.config.race_id_col: str(race_id) if race_id is not None else "",
                        self.config.horse_name_col: row_dict.get(self.config.horse_name_col),
                        "snapshot_label": "ambiguous",
                        "odds": row_dict.get(self.config.odds_col),
                        "favorite_rank": row_dict.get(self.config.favorite_rank_col),
                        "available_at": None,
                        "bet_time": bet_time.isoformat() if bet_time is not None else None,
                        "race_start_at": race_start_at.isoformat() if race_start_at is not None else None,
                        "captured_at": captured_at.isoformat() if captured_at is not None else None,
                        "plain_odds_role": None,
                        "plain_odds_ambiguous": True,
                    }
                )

        long_frame = pd.DataFrame.from_records(records)
        if not long_frame.empty and "snapshot_label" in long_frame.columns:
            long_frame["snapshot_label"] = long_frame["snapshot_label"].map(normalize_snapshot_label)
        self._long_frame = long_frame
        self._frames = OrderedDict((label, long_frame[long_frame["snapshot_label"] == label].copy()) for label in SNAPSHOT_LABELS if not long_frame.empty)
        return self._long_frame.copy()

    def _infer_available_at(
        self,
        snapshot_label: str,
        row: dict[str, Any],
        race_start_at: pd.Timestamp | None,
        bet_time: pd.Timestamp | None,
    ) -> pd.Timestamp | None:
        label = normalize_snapshot_label(snapshot_label)
        explicit = parse_timestamp(row.get(f"{label}_timestamp")) or parse_timestamp(row.get(f"{label.replace('-', '_')}_timestamp"))
        if explicit is not None:
            return explicit

        if race_start_at is None:
            return bet_time

        offset = self._time_offset(label)
        if offset is None:
            return None
        return pd.Timestamp(race_start_at - offset)

    def long_frame(self) -> pd.DataFrame:
        return self._long_frame.copy()

    def available_at(self, as_of: Any, *, labels: Iterable[str] | None = None) -> pd.DataFrame:
        if self._long_frame.empty:
            return self._long_frame.copy()
        as_of_ts = parse_timestamp(as_of)
        if as_of_ts is None:
            raise ValueError(f"Invalid as_of timestamp: {as_of!r}")
        frame = self._long_frame.copy()
        frame["available_at_ts"] = pd.to_datetime(frame["available_at"], errors="coerce")
        mask = frame["available_at_ts"].notna() & (frame["available_at_ts"] <= as_of_ts)
        if labels is not None:
            allowed = {normalize_snapshot_label(label) for label in labels}
            mask &= frame["snapshot_label"].isin(allowed)
        return frame[mask].drop(columns=["available_at_ts"])

    def split_market_phase(self) -> dict[str, pd.DataFrame]:
        frame = self._long_frame.copy()
        if frame.empty:
            return {"available_at_bet_time": frame, "final_market": frame, "post_market": frame}
        labels = frame["snapshot_label"].astype(str)
        return {
            "available_at_bet_time": frame[labels.isin(PRE_RACE_LABELS)].copy(),
            "final_market": frame[labels.isin(CLOSING_LABELS)].copy(),
            "post_market": frame[~labels.isin(PRE_RACE_LABELS + CLOSING_LABELS)].copy(),
        }

    def snapshot_timing_report(self) -> pd.DataFrame:
        if self._long_frame.empty:
            return self._long_frame.copy()
        frame = self._long_frame.copy()
        frame["available_at_ts"] = pd.to_datetime(frame["available_at"], errors="coerce")
        frame["race_start_at_ts"] = pd.to_datetime(frame["race_start_at"], errors="coerce")
        frame["available_before_race_start"] = frame["available_at_ts"].isna() | frame["race_start_at_ts"].isna() | (frame["available_at_ts"] <= frame["race_start_at_ts"])
        return frame