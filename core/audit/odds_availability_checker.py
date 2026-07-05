"""Availability checks for bet-time odds versus final market odds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    import pandas as pd
except Exception:
    pd = None

from .odds_snapshot import CLOSING_LABELS, PRE_RACE_LABELS, normalize_snapshot_label


@dataclass
class AvailabilitySummary:
    total_rows: int
    available_at_bet_time_rows: int
    final_market_rows: int
    post_market_rows: int
    missing_timestamps: int


class OddsAvailabilityChecker:
    """Verify that odds are only used when they were actually observable."""

    def annotate(
        self,
        df: pd.DataFrame,
        *,
        snapshot_label_col: str = "snapshot_label",
        available_at_col: str = "available_at",
        bet_time_col: str = "bet_time",
        race_start_col: str = "race_start_at",
    ) -> pd.DataFrame:
        frame = df.copy()
        if snapshot_label_col in frame.columns:
            frame[snapshot_label_col] = frame[snapshot_label_col].map(normalize_snapshot_label)
        else:
            frame[snapshot_label_col] = "ambiguous"

        frame["available_at_ts"] = pd.to_datetime(frame.get(available_at_col), errors="coerce")
        frame["bet_time_ts"] = pd.to_datetime(frame.get(bet_time_col), errors="coerce")
        frame["race_start_ts"] = pd.to_datetime(frame.get(race_start_col), errors="coerce")

        frame["available_at_bet_time"] = frame.apply(self._available_at_bet_time, axis=1)
        frame["final_market_odds"] = frame[snapshot_label_col].isin(CLOSING_LABELS)
        frame["post_market_info"] = ~frame[snapshot_label_col].isin(PRE_RACE_LABELS + CLOSING_LABELS)
        frame["closing_odds_contamination"] = frame["final_market_odds"] & frame["available_at_bet_time"].eq(False)
        return frame

    @staticmethod
    def _available_at_bet_time(row: pd.Series) -> bool:
        available = row.get("available_at_ts")
        bet_time = row.get("bet_time_ts")
        race_start = row.get("race_start_ts")

        if pd.isna(available):
            return False
        if not pd.isna(bet_time):
            return available <= bet_time
        if not pd.isna(race_start):
            return available <= race_start
        return False

    def verify(self, df: pd.DataFrame) -> dict[str, Any]:
        frame = self.annotate(df)
        summary = AvailabilitySummary(
            total_rows=len(frame),
            available_at_bet_time_rows=int(frame["available_at_bet_time"].sum()),
            final_market_rows=int(frame["final_market_odds"].sum()),
            post_market_rows=int(frame["post_market_info"].sum()),
            missing_timestamps=int(frame["available_at_ts"].isna().sum()),
        )
        contamination = frame[frame["closing_odds_contamination"]].copy()
        return {
            "summary": summary.__dict__,
            "contaminated_rows": contamination,
            "contaminated_count": len(contamination),
            "safe_rows": frame[frame["available_at_bet_time"]].copy(),
            "frame": frame,
        }

    def split(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        frame = self.annotate(df)
        return {
            "available_at_bet_time": frame[frame["available_at_bet_time"]].copy(),
            "final_market": frame[frame["final_market_odds"]].copy(),
            "post_market": frame[frame["post_market_info"]].copy(),
        }