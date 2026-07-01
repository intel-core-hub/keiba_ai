from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.mock_real_data_provider_server import create_app


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_mock_server_serves_schedule_odds_and_results(tmp_path):
    _write_json(
        tmp_path / "today_races.json",
        [
            {
                "race_id": "R1",
                "race_start_at_utc": "2026-06-02T03:00:00+00:00",
                "venue": "TOKYO",
                "race_number": "01",
            },
            {
                "race_id": "R2",
                "race_start_at_utc": "2026-06-03T03:00:00+00:00",
                "venue": "KYOTO",
                "race_number": "02",
            },
        ],
    )
    _write_json(tmp_path / "odds" / "R1.json", [{"race_id": "R1", "horse_id": "H01", "odds": 3.4}])
    _write_json(
        tmp_path / "results" / "R1.json",
        [{"race_id": "R1", "horse_id": "H01", "finish_position": 1, "is_win": True, "win_payout": 360}],
    )

    client = TestClient(
        create_app(
            schedule_path=tmp_path / "today_races.json",
            odds_dir=tmp_path / "odds",
            results_dir=tmp_path / "results",
        )
    )

    schedule = client.get("/schedule", params={"target_date": "2026-06-02"})
    odds = client.get("/odds/R1")
    results = client.get("/results/R1")

    assert schedule.status_code == 200
    assert schedule.json()["races"] == [
        {
            "race_id": "R1",
            "race_start_at_utc": "2026-06-02T03:00:00+00:00",
            "venue": "TOKYO",
            "race_number": "01",
            "source": "mock_api",
        }
    ]
    assert odds.status_code == 200
    assert odds.json()["odds"][0]["source"] == "mock_api"
    assert results.status_code == 200
    assert results.json()["results"][0]["win_payout"] == 360


def test_mock_server_returns_404_for_missing_fixture(tmp_path):
    _write_json(tmp_path / "today_races.json", [])
    client = TestClient(
        create_app(
            schedule_path=tmp_path / "today_races.json",
            odds_dir=tmp_path / "odds",
            results_dir=tmp_path / "results",
        )
    )

    response = client.get("/odds/UNKNOWN")

    assert response.status_code == 404
    assert "missing odds fixture" in response.json()["detail"]
