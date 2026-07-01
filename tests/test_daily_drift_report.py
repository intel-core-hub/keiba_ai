from __future__ import annotations

import csv
import json
from pathlib import Path

from core.data_sources.feature_snapshot_store import FeatureSnapshotStore
from scripts.daily_drift_report import build_daily_drift_report


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_daily_drift_report_outputs_psi_and_prediction_summary(tmp_path):
    baseline = tmp_path / "historical.csv"
    _write_csv(
        baseline,
        [
            {"early_odds": 3.0, "horse_win_rate": 0.1},
            {"early_odds": 4.0, "horse_win_rate": 0.2},
            {"early_odds": 5.0, "horse_win_rate": 0.3},
        ],
    )
    store = FeatureSnapshotStore(tmp_path / "feature_snapshots")
    for idx, odds in enumerate((3.1, 4.1, 5.1), start=1):
        store.save(
            race_id="R1",
            horse_id=f"H{idx:02d}",
            features={"early_odds": odds, "horse_win_rate": 0.1 * idx},
            source_cutoff_time_utc="2026-06-02T01:00:00+00:00",
            snapshot_time_utc=f"2026-06-02T01:0{idx}:00+00:00",
        )
    decision_log = tmp_path / "decisions.jsonl"
    decision_log.write_text(
        json.dumps({"event_type": "BetSubmitted", "occurred_at_utc": "2026-06-02T01:10:00+00:00", "payload": {"race_id": "R1", "selection_id": "H01"}}) + "\n",
        encoding="utf-8",
    )
    results = tmp_path / "race_results.csv"
    _write_csv(results, [{"race_id": "R1", "horse_id": "H01", "result_time": "2026-06-02T02:00:00+00:00"}])

    report = build_daily_drift_report(
        baseline=baseline,
        feature_snapshots=tmp_path / "feature_snapshots",
        decision_log=decision_log,
        results=results,
        outdir=tmp_path / "reports" / "drift",
        top_features=["early_odds", "horse_win_rate"],
    )

    psi_rows = list(csv.DictReader((tmp_path / "reports" / "drift" / "daily_feature_psi.csv").open(newline="", encoding="utf-8")))
    prediction_rows = list(csv.DictReader((tmp_path / "reports" / "drift" / "daily_prediction_summary.csv").open(newline="", encoding="utf-8")))
    assert report["current_rows"] == 3
    assert {row["feature"] for row in psi_rows} == {"early_odds", "horse_win_rate"}
    assert prediction_rows[0]["joined_rows"] == "1"


def test_daily_drift_report_marks_insufficient_data(tmp_path):
    baseline = tmp_path / "historical.csv"
    _write_csv(baseline, [{"early_odds": 3.0}])

    report = build_daily_drift_report(
        baseline=baseline,
        feature_snapshots=tmp_path / "missing_snapshots",
        decision_log=tmp_path / "missing_decisions.jsonl",
        results=tmp_path / "missing_results.csv",
        outdir=tmp_path / "reports" / "drift",
        top_features=["early_odds"],
    )

    status = json.loads((tmp_path / "reports" / "drift" / "daily_drift_status.json").read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert status["status"] == "insufficient_data"
