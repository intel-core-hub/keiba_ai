from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import requests
import yaml

from core.betting.bet_types import default_registry, normalize_legacy_win_record
from core.data_sources.base import DataProvider, OddsRow, RaceSchedule, ResultRow
from core.data_sources.provider_errors import ProviderDataError, ProviderUnavailableError


def _parse_utc_datetime(value: Any, *, field: str) -> datetime:
    if value is None or value == "":
        raise ProviderDataError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderDataError(f"{field} is not ISO8601: {value}") from exc
    if parsed.tzinfo is None:
        raise ProviderDataError(f"{field} must include timezone: {value}")
    return parsed.astimezone(timezone.utc)


def _bool_like(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "win", "winner"}:
        return True
    if text in {"0", "false", "no", "n", "lose", "lost"}:
        return False
    raise ProviderDataError(f"is_win must be boolean-like: {value}")


def _float_value(value: Any, *, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderDataError(f"{field} must be numeric: {value}") from exc


def _read_hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def _extract_rows(payload: Any, *, field: str, kind: str) -> list[dict[str, Any]]:
    rows: Any = payload
    if isinstance(payload, dict):
        rows = payload.get(field) if field in payload else [payload]
    if not isinstance(rows, list):
        raise ProviderDataError(f"{kind} JSON must be a list, object, or object with '{field}' list")
    for item in rows:
        if not isinstance(item, dict):
            raise ProviderDataError(f"{kind} row must be an object")
    return rows


def _required_text(item: dict[str, Any], field: str, *, kind: str) -> str:
    value = str(item.get(field) or "").strip()
    if not value:
        raise ProviderDataError(f"{kind} row missing {field}")
    return value


def _maybe_int(value: Any, *, field: str, race_id: str) -> int | None:
    if value in ("", None):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ProviderDataError(f"invalid {field} for {race_id}: {value}") from exc


def _append_query(url: str, **params: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        query.setdefault(key, value)
    return urlunparse(parsed._replace(query=urlencode(query)))


@dataclass(frozen=True)
class HTTPProviderConfig:
    provider: str
    schedule_url: str
    odds_url_template: str
    results_url_template: str
    timeout_seconds: float = 10.0
    retry_limit: int = 2
    retry_backoff_seconds: float = 0.0
    user_agent: str = "keiba-ai-evidence-collector/0.1"


def load_http_provider_config(path: Path) -> HTTPProviderConfig:
    if not path.exists():
        raise ProviderUnavailableError(f"missing provider config: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProviderDataError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ProviderDataError("http provider config must be an object")

    provider = str(payload.get("provider") or "").strip().lower()
    if provider and provider != "http":
        raise ProviderDataError(f"unsupported provider in config: {provider}")

    timeout_seconds = _float_value(payload.get("timeout_seconds", 10), field="timeout_seconds")
    retry_limit_raw = payload.get("retry_limit", 2)
    try:
        retry_limit = int(retry_limit_raw)
    except (TypeError, ValueError) as exc:
        raise ProviderDataError(f"retry_limit must be an integer: {retry_limit_raw}") from exc
    if retry_limit < 0:
        raise ProviderDataError(f"retry_limit must be >= 0: {retry_limit}")

    retry_backoff_seconds = _float_value(
        payload.get("retry_backoff_seconds", 0.0),
        field="retry_backoff_seconds",
    )
    if retry_backoff_seconds < 0:
        raise ProviderDataError(f"retry_backoff_seconds must be >= 0: {retry_backoff_seconds}")

    return HTTPProviderConfig(
        provider="http",
        schedule_url=_required_text(payload, "schedule_url", kind="config"),
        odds_url_template=_required_text(payload, "odds_url_template", kind="config"),
        results_url_template=_required_text(payload, "results_url_template", kind="config"),
        timeout_seconds=timeout_seconds,
        retry_limit=retry_limit,
        retry_backoff_seconds=retry_backoff_seconds,
        user_agent=str(payload.get("user_agent") or "keiba-ai-evidence-collector/0.1"),
    )


def build_http_provider_from_yaml(
    path: Path,
    *,
    observed_at_utc: datetime | None = None,
    session: requests.Session | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> "HTTPProvider":
    return HTTPProvider(
        load_http_provider_config(path),
        observed_at_utc=observed_at_utc,
        session=session,
        now_fn=now_fn,
    )


class HTTPProvider(DataProvider):
    def __init__(
        self,
        config: HTTPProviderConfig,
        *,
        observed_at_utc: datetime | None = None,
        session: requests.Session | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.observed_at_utc = observed_at_utc.astimezone(timezone.utc) if observed_at_utc else None
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": config.user_agent, "Accept": "application/json"})
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return self._now_fn().astimezone(timezone.utc)

    def _build_schedule_url(self, target_date: date) -> str:
        if "{target_date}" in self.config.schedule_url:
            return self.config.schedule_url.format(target_date=target_date.isoformat())
        return _append_query(self.config.schedule_url, target_date=target_date.isoformat())

    def _build_race_url(self, template: str, race_id: str) -> str:
        return template.format(race_id=quote(race_id, safe=""))

    def _request_json(self, url: str, *, kind: str) -> tuple[Any, str, float, datetime]:
        attempts = self.config.retry_limit + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            observed_at = self.observed_at_utc or self._now()
            started = time.perf_counter()
            try:
                response = self._session.request("GET", url, timeout=self.config.timeout_seconds)
                latency_ms = (time.perf_counter() - started) * 1000.0

                if response.status_code >= 400:
                    error = ProviderUnavailableError(
                        f"{kind} request failed with HTTP {response.status_code}: {url}"
                    )
                    if attempt < attempts and response.status_code in {408, 429, 500, 502, 503, 504}:
                        last_error = error
                        self._sleep_before_retry(attempt)
                        continue
                    raise error

                raw_bytes = response.content
                try:
                    payload = json.loads(response.text)
                except json.JSONDecodeError as exc:
                    raise ProviderDataError(f"invalid JSON for {kind}: {exc}") from exc
                return payload, _read_hash(raw_bytes), latency_ms, observed_at
            except ProviderDataError:
                raise
            except requests.Timeout as exc:
                last_error = exc
                if attempt < attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise ProviderUnavailableError(f"{kind} request timed out after {attempts} attempts: {url}") from exc
            except requests.RequestException as exc:
                last_error = exc
                if attempt < attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise ProviderUnavailableError(f"{kind} request failed after {attempts} attempts: {url}") from exc

        raise ProviderUnavailableError(f"{kind} request failed: {url}") from last_error

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.config.retry_backoff_seconds <= 0:
            return
        time.sleep(self.config.retry_backoff_seconds * attempt)

    def list_today_races(self, target_date: date) -> list[RaceSchedule]:
        payload, _, _, _ = self._request_json(self._build_schedule_url(target_date), kind="schedule")
        rows = _extract_rows(payload, field="races", kind="schedule")
        races: list[RaceSchedule] = []
        for item in rows:
            race_id = _required_text(item, "race_id", kind="schedule")
            start = _parse_utc_datetime(item.get("race_start_at_utc"), field="race_start_at_utc")
            if start.date() != target_date:
                continue
            races.append(
                RaceSchedule(
                    race_id=race_id,
                    race_start_at_utc=start,
                    venue=str(item.get("venue")) if item.get("venue") is not None else None,
                    race_number=str(item.get("race_number")) if item.get("race_number") is not None else None,
                    source=str(item.get("source") or "http_provider"),
                )
            )
        return races

    def fetch_odds(self, race_id: str) -> list[OddsRow]:
        payload, raw_hash, latency_ms, observed_at = self._request_json(
            self._build_race_url(self.config.odds_url_template, race_id),
            kind="odds",
        )
        rows = _extract_rows(payload, field="odds", kind="odds")
        parsed: list[OddsRow] = []
        registry = default_registry()
        for item in rows:
            if not item.get("bet_type") and not item.get("legs") and not (item.get("horse_id") or item.get("selection_id")):
                raise ProviderDataError(f"odds row missing horse_id for {race_id}")
            try:
                normalized = normalize_legacy_win_record(
                    {**item, "race_id": item.get("race_id") or race_id},
                    registry=registry,
                )
            except ValueError as exc:
                raise ProviderDataError(str(exc)) from exc
            horse_id = str(item.get("horse_id") or item.get("selection_id") or normalized["legs"][0]).strip()

            snapshot_value = item.get("snapshot_at_utc") or item.get("snapshot_time")
            source = str(item.get("source") or "http_provider")
            if snapshot_value in (None, ""):
                snapshot_at = observed_at
                source = "http_provider_observed_at"
            else:
                snapshot_at = _parse_utc_datetime(snapshot_value, field="snapshot_at_utc")

            parsed.append(
                OddsRow(
                    race_id=str(item.get("race_id") or race_id),
                    horse_id=horse_id,
                    odds=_float_value(item.get("odds"), field="odds"),
                    snapshot_at_utc=snapshot_at,
                    source=source,
                    provider_latency_ms=_float_value(
                        item.get("provider_latency_ms", latency_ms),
                        field="provider_latency_ms",
                    ),
                    raw_payload_hash=raw_hash,
                    bet_type=normalized["bet_type"],
                    legs=tuple(normalized["legs"]),
                    ordered=bool(normalized["ordered"]),
                )
            )
        return parsed

    def fetch_race_result(self, race_id: str) -> list[ResultRow]:
        payload, raw_hash, latency_ms, observed_at = self._request_json(
            self._build_race_url(self.config.results_url_template, race_id),
            kind="results",
        )
        rows = _extract_rows(payload, field="results", kind="result")
        parsed: list[ResultRow] = []
        registry = default_registry()
        for item in rows:
            if not item.get("bet_type") and not item.get("legs") and not (item.get("horse_id") or item.get("selection_id")):
                raise ProviderDataError(f"result row missing horse_id for {race_id}")
            try:
                normalized = normalize_legacy_win_record(
                    {**item, "race_id": item.get("race_id") or race_id},
                    registry=registry,
                )
            except ValueError as exc:
                raise ProviderDataError(str(exc)) from exc
            horse_id = str(item.get("horse_id") or item.get("selection_id") or normalized["legs"][0]).strip()

            result_time_value = item.get("result_time_utc") or item.get("result_time")
            source = str(item.get("source") or "http_provider")
            if result_time_value in (None, ""):
                result_time = observed_at
                source = "http_provider_observed_at"
            else:
                result_time = _parse_utc_datetime(result_time_value, field="result_time_utc")

            parsed.append(
                ResultRow(
                    race_id=str(item.get("race_id") or race_id),
                    horse_id=horse_id,
                    finish_position=_maybe_int(item.get("finish_position"), field="finish_position", race_id=race_id),
                    is_win=_bool_like(item.get("is_win")) if item.get("is_win") is not None else False,
                    win_payout=_float_value(item.get("win_payout", item.get("payout", 0)), field="payout"),
                    result_time_utc=result_time,
                    source=source,
                    provider_latency_ms=_float_value(
                        item.get("provider_latency_ms", latency_ms),
                        field="provider_latency_ms",
                    ),
                    raw_payload_hash=raw_hash,
                    bet_type=normalized["bet_type"],
                    legs=tuple(normalized["legs"]),
                    ordered=bool(normalized["ordered"]),
                    payout=_float_value(item.get("payout", item.get("win_payout", 0)), field="payout"),
                )
            )
        return parsed
