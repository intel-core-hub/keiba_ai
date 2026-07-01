from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from core.betting.bet_types import default_registry, normalize_legacy_win_record
from core.data_sources.base import DataProvider, OddsRow, RaceSchedule, ResultRow
from core.data_sources.provider_errors import ProviderDataError, ProviderUnavailableError


def parse_utc_datetime(value: Any, *, field: str) -> datetime:
    if value is None or value == "":
        raise ProviderDataError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderDataError(f"{field} is not ISO8601: {value}") from exc
    if parsed.tzinfo is None:
        raise ProviderDataError(f"{field} must include timezone: {value}")
    return parsed.astimezone(timezone.utc)


def canonical_hash(payload: Any) -> str:
    import hashlib

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise ProviderUnavailableError(f"missing provider file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProviderDataError(f"invalid JSON in {path}: {exc}") from exc


def _extract_rows(payload: Any, *, field: str, kind: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        if field in payload:
            rows = payload.get(field)
        else:
            rows = [payload]
    else:
        raise ProviderDataError(f"{kind} JSON must be a list, object, or object with '{field}' list")
    if not isinstance(rows, list):
        raise ProviderDataError(f"{kind} JSON '{field}' must be a list")
    for item in rows:
        if not isinstance(item, dict):
            raise ProviderDataError(f"{kind} row must be an object")
    return rows


class LocalFileProvider(DataProvider):
    def __init__(
        self,
        *,
        schedule_path: Path,
        odds_dir: Path | None = None,
        results_dir: Path | None = None,
        snapshot_at_utc: datetime | None = None,
        result_time_utc: datetime | None = None,
    ) -> None:
        self.schedule_path = schedule_path
        self.odds_dir = odds_dir
        self.results_dir = results_dir
        self.snapshot_at_utc = snapshot_at_utc.astimezone(timezone.utc) if snapshot_at_utc else None
        self.result_time_utc = result_time_utc.astimezone(timezone.utc) if result_time_utc else None

    def list_today_races(self, target_date: date) -> list[RaceSchedule]:
        payload = _load_json(self.schedule_path)
        if not isinstance(payload, list):
            raise ProviderDataError("schedule JSON must be a list")
        races: list[RaceSchedule] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ProviderDataError("schedule row must be an object")
            race_id = str(item.get("race_id") or "").strip()
            if not race_id:
                raise ProviderDataError("schedule row missing race_id")
            start = parse_utc_datetime(item.get("race_start_at_utc"), field="race_start_at_utc")
            if start.date() != target_date:
                continue
            races.append(
                RaceSchedule(
                    race_id=race_id,
                    race_start_at_utc=start,
                    venue=str(item.get("venue")) if item.get("venue") is not None else None,
                    race_number=str(item.get("race_number")) if item.get("race_number") is not None else None,
                    source=str(item.get("source") or "local_file"),
                )
            )
        return races

    def fetch_odds(self, race_id: str) -> list[OddsRow]:
        if self.odds_dir is None:
            raise ProviderUnavailableError("odds_dir is not configured")
        path = self.odds_dir / f"{race_id}.json"
        started = time.perf_counter()
        payload = _load_json(path)
        latency_ms = (time.perf_counter() - started) * 1000.0
        rows_payload = _extract_rows(payload, field="odds", kind="odds")
        rows: list[OddsRow] = []
        registry = default_registry()
        for item in rows_payload:
            if not item.get("bet_type") and not item.get("legs") and not (item.get("horse_id") or item.get("selection_id")):
                raise ProviderDataError(f"odds row missing horse_id for {race_id}")
            try:
                normalized = normalize_legacy_win_record(
                    {**item, "race_id": item.get("race_id") or race_id},
                    registry=registry,
                )
            except ValueError as exc:
                raise ProviderDataError(str(exc)) from exc
            snapshot_at = (
                parse_utc_datetime(item.get("snapshot_time") or item.get("snapshot_at_utc"), field="snapshot_time")
                if item.get("snapshot_time") or item.get("snapshot_at_utc")
                else self.snapshot_at_utc
            )
            odds_value = item.get("odds")
            try:
                odds = float(odds_value)
            except (TypeError, ValueError) as exc:
                raise ProviderDataError(f"invalid odds for {race_id}: {odds_value}") from exc
            rows.append(
                OddsRow(
                    race_id=str(item.get("race_id") or race_id),
                    horse_id=str(item.get("horse_id") or item.get("selection_id") or normalized["legs"][0]).strip(),
                    odds=odds,
                    snapshot_at_utc=snapshot_at,
                    source=str(item.get("source") or "local_file"),
                    provider_latency_ms=float(item.get("provider_latency_ms", latency_ms) or latency_ms),
                    raw_payload_hash=str(item.get("raw_payload_hash") or canonical_hash(item)),
                    bet_type=normalized["bet_type"],
                    legs=tuple(normalized["legs"]),
                    ordered=bool(normalized["ordered"]),
                )
            )
        return rows

    def fetch_race_result(self, race_id: str) -> list[ResultRow]:
        if self.results_dir is None:
            raise ProviderUnavailableError("results_dir is not configured")
        path = self.results_dir / f"{race_id}.json"
        started = time.perf_counter()
        payload = _load_json(path)
        latency_ms = (time.perf_counter() - started) * 1000.0
        rows_payload = _extract_rows(payload, field="results", kind="result")
        rows: list[ResultRow] = []
        registry = default_registry()
        for item in rows_payload:
            if not item.get("bet_type") and not item.get("legs") and not (item.get("horse_id") or item.get("selection_id")):
                raise ProviderDataError(f"result row missing horse_id for {race_id}")
            try:
                normalized = normalize_legacy_win_record(
                    {**item, "race_id": item.get("race_id") or race_id},
                    registry=registry,
                )
            except ValueError as exc:
                raise ProviderDataError(str(exc)) from exc
            result_time = (
                parse_utc_datetime(item.get("result_time") or item.get("result_time_utc"), field="result_time")
                if item.get("result_time") or item.get("result_time_utc")
                else self.result_time_utc
            )
            payout_value = item.get("win_payout", item.get("payout", 0))
            try:
                win_payout = float(payout_value)
            except (TypeError, ValueError) as exc:
                raise ProviderDataError(f"invalid payout for {race_id}: {payout_value}") from exc
            finish_position = item.get("finish_position")
            if finish_position in ("", None):
                position = None
            else:
                try:
                    position = int(finish_position)
                except (TypeError, ValueError) as exc:
                    raise ProviderDataError(f"invalid finish_position for {race_id}: {finish_position}") from exc
            rows.append(
                ResultRow(
                    race_id=str(item.get("race_id") or race_id),
                    horse_id=str(item.get("horse_id") or item.get("selection_id") or normalized["legs"][0]).strip(),
                    finish_position=position,
                    is_win=_bool(item.get("is_win")) if item.get("is_win") is not None else False,
                    win_payout=win_payout,
                    result_time_utc=result_time,
                    source=str(item.get("source") or "local_file"),
                    provider_latency_ms=float(item.get("provider_latency_ms", latency_ms) or latency_ms),
                    raw_payload_hash=str(item.get("raw_payload_hash") or canonical_hash(item)),
                    bet_type=normalized["bet_type"],
                    legs=tuple(normalized["legs"]),
                    ordered=bool(normalized["ordered"]),
                    payout=win_payout,
                )
            )
        return rows


def _bool(value: Any) -> bool:
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
