from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from core.data_sources.http_provider import (
    HTTPProvider,
    HTTPProviderConfig,
    build_http_provider_from_yaml,
)
from core.data_sources.provider_errors import ProviderDataError, ProviderUnavailableError


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = "[]") -> None:
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")


def _json_response(payload: object, *, status_code: int = 200) -> _FakeResponse:
    return _FakeResponse(status_code=status_code, text=json.dumps(payload, ensure_ascii=False))


def _config(**overrides) -> HTTPProviderConfig:
    defaults = {
        "provider": "http",
        "schedule_url": "http://provider.test/schedule",
        "odds_url_template": "http://provider.test/odds/{race_id}",
        "results_url_template": "http://provider.test/results/{race_id}",
        "timeout_seconds": 0.01,
        "retry_limit": 2,
        "retry_backoff_seconds": 0.0,
        "user_agent": "keiba-ai-test/0.1",
    }
    defaults.update(overrides)
    return HTTPProviderConfig(**defaults)


def test_http_provider_schedule_fetches_and_filters_target_date(tmp_path, monkeypatch):
    config_path = tmp_path / "real_data_provider.yaml"
    config_path.write_text(
        "\n".join(
            [
                "provider: http",
                'schedule_url: "http://provider.test/schedule"',
                'odds_url_template: "http://provider.test/odds/{race_id}"',
                'results_url_template: "http://provider.test/results/{race_id}"',
                "timeout_seconds: 1",
                "retry_limit: 1",
                "retry_backoff_seconds: 0",
                'user_agent: "keiba-ai-test/0.1"',
            ]
        ),
        encoding="utf-8",
    )

    def fake_request(self, method, url, timeout, **kwargs):
        assert method == "GET"
        assert "target_date=2026-06-02" in url
        return _json_response(
            {
                "races": [
                    {
                        "race_id": "R1",
                        "race_start_at_utc": "2026-06-02T01:30:00+00:00",
                        "venue": "TOKYO",
                        "race_number": "01",
                    },
                    {
                        "race_id": "R2",
                        "race_start_at_utc": "2026-06-03T01:30:00+00:00",
                        "venue": "KYOTO",
                        "race_number": "02",
                    },
                ]
            }
        )

    monkeypatch.setattr("requests.Session.request", fake_request)

    provider = build_http_provider_from_yaml(config_path)
    races = provider.list_today_races(date(2026, 6, 2))

    assert [race.race_id for race in races] == ["R1"]
    assert races[0].venue == "TOKYO"
    assert races[0].source == "http_provider"


def test_http_provider_fetch_odds_records_latency_hash_and_observed_timestamp(monkeypatch):
    observed_at = datetime(2026, 6, 2, 1, 0, tzinfo=timezone.utc)
    response_payload = [
        {
            "race_id": "R1",
            "horse_id": "H01",
            "odds": 3.4,
        }
    ]
    response = _json_response(response_payload)

    def fake_request(self, method, url, timeout, **kwargs):
        assert url == "http://provider.test/odds/R1"
        return response

    monkeypatch.setattr("requests.Session.request", fake_request)

    provider = HTTPProvider(_config(), observed_at_utc=observed_at)
    rows = provider.fetch_odds("R1")

    assert len(rows) == 1
    assert rows[0].race_id == "R1"
    assert rows[0].horse_id == "H01"
    assert rows[0].snapshot_at_utc == observed_at
    assert rows[0].source == "http_provider_observed_at"
    assert rows[0].provider_latency_ms is not None
    assert rows[0].provider_latency_ms >= 0
    assert rows[0].raw_payload_hash == hashlib.sha256(response.text.encode("utf-8")).hexdigest()


def test_http_provider_fetch_race_result_records_result_rows(monkeypatch):
    observed_at = datetime(2026, 6, 2, 5, 0, tzinfo=timezone.utc)

    def fake_request(self, method, url, timeout, **kwargs):
        assert url == "http://provider.test/results/R1"
        return _json_response(
            {
                "results": [
                    {
                        "horse_id": "H01",
                        "finish_position": 1,
                        "is_win": True,
                        "win_payout": 360,
                    },
                    {
                        "horse_id": "H02",
                        "finish_position": 5,
                        "is_win": "false",
                        "win_payout": 0,
                        "result_time_utc": "2026-06-02T05:05:00+00:00",
                        "source": "contract_api",
                    },
                ]
            }
        )

    monkeypatch.setattr("requests.Session.request", fake_request)

    provider = HTTPProvider(_config(), observed_at_utc=observed_at)
    rows = provider.fetch_race_result("R1")

    assert [row.horse_id for row in rows] == ["H01", "H02"]
    assert rows[0].result_time_utc == observed_at
    assert rows[0].source == "http_provider_observed_at"
    assert rows[1].source == "contract_api"
    assert rows[1].finish_position == 5
    assert rows[1].provider_latency_ms is not None


def test_http_provider_timeout_retries_then_raises(monkeypatch):
    calls = {"count": 0}

    def fake_request(self, method, url, timeout, **kwargs):
        calls["count"] += 1
        raise __import__("requests").Timeout("too slow")

    monkeypatch.setattr("requests.Session.request", fake_request)

    provider = HTTPProvider(_config(retry_limit=2))
    with pytest.raises(ProviderUnavailableError, match="timed out"):
        provider.fetch_odds("R1")

    assert calls["count"] == 3


def test_http_provider_rejects_malformed_json(monkeypatch):
    def fake_request(self, method, url, timeout, **kwargs):
        return _FakeResponse(text='{"broken": ')

    monkeypatch.setattr("requests.Session.request", fake_request)

    provider = HTTPProvider(_config())
    with pytest.raises(ProviderDataError, match="invalid JSON"):
        provider.fetch_odds("R1")


def test_http_provider_rejects_missing_required_fields(monkeypatch):
    def fake_request(self, method, url, timeout, **kwargs):
        return _json_response([{"race_id": "R1", "odds": 5.2}])

    monkeypatch.setattr("requests.Session.request", fake_request)

    provider = HTTPProvider(_config())
    with pytest.raises(ProviderDataError, match="missing horse_id"):
        provider.fetch_odds("R1")


def test_http_provider_raw_payload_hash_is_stable(monkeypatch):
    body = json.dumps([{"race_id": "R1", "horse_id": "H01", "odds": 4.1}], ensure_ascii=False)

    def fake_request(self, method, url, timeout, **kwargs):
        return _FakeResponse(text=body)

    monkeypatch.setattr("requests.Session.request", fake_request)

    provider = HTTPProvider(_config(), observed_at_utc=datetime(2026, 6, 2, 1, 0, tzinfo=timezone.utc))
    first = provider.fetch_odds("R1")
    second = provider.fetch_odds("R1")

    assert first[0].raw_payload_hash == second[0].raw_payload_hash
    assert first[0].raw_payload_hash == hashlib.sha256(body.encode("utf-8")).hexdigest()
