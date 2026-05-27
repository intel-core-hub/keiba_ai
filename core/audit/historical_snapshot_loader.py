import os
import pandas as pd
from datetime import datetime


class HistoricalSnapshotLoader:
    """Load processed historical dataset and provide per-race/horse snapshots.

    Methods are conservative: they report scraped timestamps and allow
    callers to verify availability as-of a decision timestamp.
    """

    def __init__(self, path=None):
        self.path = path or os.path.join("data", "processed", "historical_dataset.csv")
        self.df = None
        if os.path.exists(self.path):
            try:
                self.df = pd.read_csv(self.path, parse_dates=["scraped_at"], low_memory=False)
            except Exception:
                self.df = pd.read_csv(self.path, low_memory=False)

    def has_data(self):
        return self.df is not None

    def get_row(self, race_id, horse_id=None, horse_name=None):
        if self.df is None:
            return None

        q = self.df[self.df["race_id"] == race_id]
        if q.empty:
            return None

        if horse_id is not None and "horse_id" in q.columns:
            q2 = q[q["horse_id"].astype(str) == str(horse_id)]
            if not q2.empty:
                return q2.iloc[0].to_dict()

        if horse_name is not None and "horse_name" in q.columns:
            q2 = q[q["horse_name"].astype(str) == str(horse_name)]
            if not q2.empty:
                return q2.iloc[0].to_dict()

        # fallback: return first matching race row
        return q.iloc[0].to_dict()

    def available_as_of(self, row, as_of_ts):
        """Return True if the row's `scraped_at` is <= as_of_ts (string or datetime)."""
        if row is None:
            return False

        scraped = row.get("scraped_at")
        if scraped is None:
            return True

        try:
            if isinstance(scraped, str):
                scraped_dt = datetime.fromisoformat(scraped)
            else:
                scraped_dt = pd.to_datetime(scraped)

            if isinstance(as_of_ts, str):
                as_of_dt = datetime.fromisoformat(as_of_ts)
            else:
                as_of_dt = pd.to_datetime(as_of_ts)

            return scraped_dt <= as_of_dt
        except Exception:
            return True
