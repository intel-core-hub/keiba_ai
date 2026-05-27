import json
from typing import Dict


class DecisionReconstruction:
    """Reconstruct the information available at decision time from logs

    Uses DecisionLogger entries (which include feature dict) and compares
    with historical snapshots when available.
    """

    def __init__(self, snapshot_loader):
        self.loader = snapshot_loader

    def reconstruct(self, decision_record: Dict):
        # primary keys
        race_id = decision_record.get("race_id")
        selection = decision_record.get("selection")
        ts = decision_record.get("timestamp")

        reconstructed = {
            "decision_id": decision_record.get("decision_id"),
            "race_id": race_id,
            "selection": selection,
            "timestamp": ts,
            "log_features": decision_record.get("features"),
            "logged_odds": decision_record.get("odds"),
            "calibration": {
                "brier": decision_record.get("brier_score"),
                "ece": decision_record.get("ece"),
                "reliability": decision_record.get("reliability"),
            },
            "snapshot_row": None,
            "snapshot_available": None,
            "mismatches": [],
        }

        if self.loader and self.loader.has_data():
            row = self.loader.get_row(race_id, horse_name=selection)
            reconstructed["snapshot_row"] = row
            reconstructed["snapshot_available"] = self.loader.available_as_of(row, ts)

            # compare key fields if both present
            if row is not None and decision_record.get("features"):
                for k, v in decision_record.get("features", {}).items():
                    if k in row:
                        # numerical compare tolerant
                        try:
                            rv = row.get(k)
                            if rv is None:
                                continue
                            if isinstance(v, (int, float)) and isinstance(rv, (int, float)):
                                if abs(float(v) - float(rv)) > 1e-6:
                                    reconstructed["mismatches"].append((k, v, rv))
                            else:
                                if str(v) != str(rv):
                                    reconstructed["mismatches"].append((k, v, rv))
                        except Exception:
                            continue

        return reconstructed
