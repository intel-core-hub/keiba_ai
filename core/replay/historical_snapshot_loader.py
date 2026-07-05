"""
historical_snapshot_loader.py

Provides utilities to load historical snapshots (odds, features, calibration)
as they were available at a given timestamp. Designed to be conservative: only
returns data whose recorded timestamp is <= the requested as_of timestamp.

This is intentionally generic and file-path driven so the production system
can wire it to its own snapshot stores.
"""
from __future__ import annotations
try:
    import pandas as pd
except Exception:
    pd = None
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any


class HistoricalSnapshotLoader:
    def __init__(
        self,
        odds_csv: Optional[Path] = None,
        features_csv: Optional[Path] = None,
        calibration_csv: Optional[Path] = None,
        timestamp_col: str = "timestamp",
    ) -> None:
        self.odds_csv = Path(odds_csv) if odds_csv else None
        self.features_csv = Path(features_csv) if features_csv else None
        self.calibration_csv = Path(calibration_csv) if calibration_csv else None
        self.timestamp_col = timestamp_col

        self._odds = None
        self._features = None
        self._calibration = None

    def _load_odds(self) -> pd.DataFrame:
        if self._odds is None:
            if not self.odds_csv or not self.odds_csv.exists():
                self._odds = pd.DataFrame()
            else:
                self._odds = pd.read_csv(self.odds_csv, parse_dates=[self.timestamp_col])
        return self._odds

    def _load_features(self) -> pd.DataFrame:
        if self._features is None:
            if not self.features_csv or not self.features_csv.exists():
                self._features = pd.DataFrame()
            else:
                self._features = pd.read_csv(self.features_csv, parse_dates=[self.timestamp_col])
        return self._features

    def _load_calibration(self) -> pd.DataFrame:
        if self._calibration is None:
            if not self.calibration_csv or not self.calibration_csv.exists():
                self._calibration = pd.DataFrame()
            else:
                self._calibration = pd.read_csv(self.calibration_csv, parse_dates=[self.timestamp_col])
        return self._calibration

    def get_latest_odds(self, as_of: datetime, race_id: Optional[Any] = None) -> pd.DataFrame:
        df = self._load_odds()
        if df.empty:
            return df
        sel = df[df[self.timestamp_col] <= as_of]
        if race_id is not None and 'race_id' in sel.columns:
            sel = sel[sel['race_id'] == race_id]
        if sel.empty:
            return sel
        # return most recent snapshot per candidate (group by race/horse if present)
        if 'race_id' in sel.columns and 'runner_id' in sel.columns:
            return sel.sort_values(self.timestamp_col).groupby(['race_id', 'runner_id']).tail(1)
        if 'race_id' in sel.columns:
            return sel.sort_values(self.timestamp_col).groupby('race_id').tail(1)
        return sel.sort_values(self.timestamp_col).tail(1)

    def get_latest_features(self, as_of: datetime, entity_id: Optional[Any] = None) -> pd.DataFrame:
        df = self._load_features()
        if df.empty:
            return df
        sel = df[df[self.timestamp_col] <= as_of]
        if entity_id is not None and 'entity_id' in sel.columns:
            sel = sel[sel['entity_id'] == entity_id]
        # heuristic grouping
        if 'entity_id' in sel.columns:
            return sel.sort_values(self.timestamp_col).groupby('entity_id').tail(1)
        return sel.sort_values(self.timestamp_col).tail(1)

    def get_calibration_state(self, as_of: datetime) -> pd.DataFrame:
        df = self._load_calibration()
        if df.empty:
            return df
        sel = df[df[self.timestamp_col] <= as_of]
        return sel.sort_values(self.timestamp_col).tail(1)
