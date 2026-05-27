import csv
from datetime import datetime


class ReplayValidator:
    """Perform sanity checks on reconstructed decisions."""

    def __init__(self):
        pass

    def timestamp_anomaly(self, reconstructed):
        # snapshot_available False indicates scraped_at > decision time
        if reconstructed.get("snapshot_available") is False:
            return True, "snapshot_after_decision"
        return False, None

    def feature_mismatch(self, reconstructed):
        mism = reconstructed.get("mismatches") or []
        if len(mism) > 0:
            return True, f"mismatched_features:{[m[0] for m in mism]}"
        return False, None

    def impossible_decision(self, reconstructed):
        # e.g., decision BET when expected_value is None or negative but bet placed
        rec = reconstructed
        decision = rec.get("decision")
        # keep conservative: check logged_odds and snapshot
        if rec.get("logged_odds") is None and rec.get("snapshot_row") is None:
            return True, "no_odds_info"
        return False, None
