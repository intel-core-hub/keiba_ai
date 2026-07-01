from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.data_sources.provider_errors import ProviderUnavailableError
from scripts.real_data_gateway_server import build_provider_from_gateway_config, create_app


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_gateway_config(path: Path, tmp_path: Path, *, backend: str = "local_file") -> None:
    path.write_text(
        "\n".join(
            [
                f"backend: {backend}",
                'source_label: "approved_local_gateway"',
                "local_file:",
                f'  schedule_path: "{(tmp_path / "today_races.json").as_posix()}"',
                f'  odds_dir: "{(tmp_path / "odds").as_posix()}"',
                f'  results_dir: "{(tmp_path / "results").as_posix()}"',
                '  snapshot_at_utc: "2026-06-02T02:30:00+00:00"',
                '  result_time_utc: "2026-06-02T05:00:00+00:00"',
            ]
        ),
        encoding="utf-8",
    )


def test_gateway_serves_local_file_backend_in_http_provider_shape(tmp_path):
    _write_json(
        tmp_path / "today_races.json",
        [
            {
                "race_id": "R1",
                "race_start_at_utc": "2026-06-02T03:00:00+00:00",
                "venue": "TOKYO",
                "race_number": "01",
            }
        ],
    )
    _write_json(tmp_path / "odds" / "R1.json", [{"race_id": "R1", "horse_id": "H01", "odds": 3.4}])
    _write_json(
        tmp_path / "results" / "R1.json",
        [{"race_id": "R1", "horse_id": "H01", "finish_position": 1, "is_win": True, "win_payout": 360}],
    )
    config_path = tmp_path / "gateway.yaml"
    _write_gateway_config(config_path, tmp_path)

    provider, backend, source_label = build_provider_from_gateway_config(config_path)
    client = TestClient(create_app(provider=provider, backend=backend, source_label=source_label))

    assert client.get("/health").json() == {
        "status": "ok",
        "backend": "local_file",
        "source": "approved_local_gateway",
    }

    schedule = client.get("/schedule", params={"target_date": "2026-06-02"})
    odds = client.get("/odds/R1")
    results = client.get("/results/R1")

    assert schedule.status_code == 200
    assert schedule.json()["races"][0]["source"] == "approved_local_gateway"
    assert schedule.json()["races"][0]["race_start_at_utc"] == "2026-06-02T03:00:00+00:00"
    assert odds.status_code == 200
    assert odds.json()["odds"][0]["snapshot_at_utc"] == "2026-06-02T02:30:00+00:00"
    assert odds.json()["odds"][0]["source"] == "approved_local_gateway"
    assert results.status_code == 200
    assert results.json()["results"][0]["result_time_utc"] == "2026-06-02T05:00:00+00:00"


def test_gateway_reports_missing_local_file_as_unavailable(tmp_path):
    config_path = tmp_path / "gateway.yaml"
    _write_gateway_config(config_path, tmp_path)
    provider, backend, source_label = build_provider_from_gateway_config(config_path)
    client = TestClient(create_app(provider=provider, backend=backend, source_label=source_label))

    response = client.get("/schedule", params={"target_date": "2026-06-02"})

    assert response.status_code == 503
    assert "missing provider file" in response.json()["detail"]


def test_gateway_rejects_invalid_target_date_as_bad_request(tmp_path):
    config_path = tmp_path / "gateway.yaml"
    _write_gateway_config(config_path, tmp_path)
    provider, backend, source_label = build_provider_from_gateway_config(config_path)
    client = TestClient(create_app(provider=provider, backend=backend, source_label=source_label))

    response = client.get("/schedule", params={"target_date": "not-a-date"})

    assert response.status_code == 400
    assert "target_date must be YYYY-MM-DD" in response.json()["detail"]


def test_gateway_contract_api_backend_requires_explicit_adapter(tmp_path):
    config_path = tmp_path / "gateway.yaml"
    _write_gateway_config(config_path, tmp_path, backend="contract_api")

    with pytest.raises(ProviderUnavailableError, match="not implemented"):
        build_provider_from_gateway_config(config_path)
