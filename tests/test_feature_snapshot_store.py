from __future__ import annotations

import json

import pytest

from core.data_sources.feature_snapshot_store import FeatureSnapshotStore


def test_feature_snapshot_store_writes_append_only_stable_hash(tmp_path):
    store = FeatureSnapshotStore(tmp_path / "feature_snapshots")
    kwargs = {
        "race_id": "R1",
        "horse_id": "H01",
        "features": {"early_odds": 3.6, "horse_win_rate": 0.12},
        "source_cutoff_time_utc": "2026-06-02T01:00:00+00:00",
        "snapshot_time_utc": "2026-06-02T01:01:00+00:00",
    }

    first = store.save(**kwargs)
    second = store.save(**kwargs)

    path = tmp_path / "feature_snapshots" / "2026-06-02" / "R1.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert first == second
    assert len(rows) == 2
    assert rows[0]["feature_snapshot_hash"] == first


def test_feature_snapshot_store_rejects_contamination_keys_and_missing_cutoff(tmp_path):
    store = FeatureSnapshotStore(tmp_path / "feature_snapshots")

    with pytest.raises(ValueError, match="forbidden post-race"):
        store.save(
            race_id="R1",
            horse_id="H01",
            features={"nested": {"win_payout": 360}},
            source_cutoff_time_utc="2026-06-02T01:00:00+00:00",
        )

    with pytest.raises(Exception, match="source_cutoff_time_utc"):
        store.save(
            race_id="R1",
            horse_id="H01",
            features={"early_odds": 3.6},
            source_cutoff_time_utc="",
        )
