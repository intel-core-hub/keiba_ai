from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Query

from core.data_sources.base import DataProvider, OddsRow, RaceSchedule, ResultRow
from core.data_sources.local_file_provider import LocalFileProvider, parse_utc_datetime
from core.data_sources.provider_errors import ProviderDataError, ProviderUnavailableError


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _parse_date(value: str) -> date:
    try:
        return datetime.fromisoformat(value).date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"target_date must be YYYY-MM-DD: {value}") from exc


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ProviderUnavailableError(f"missing gateway config: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProviderDataError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProviderDataError("gateway config must be an object")
    return payload


def _optional_datetime(payload: dict[str, Any], field: str) -> datetime | None:
    value = payload.get(field)
    if value in (None, ""):
        return None
    return parse_utc_datetime(value, field=field)


def build_provider_from_gateway_config(config_path: Path) -> tuple[DataProvider, str, str]:
    payload = _load_config(config_path)
    backend = str(payload.get("backend") or "").strip().lower()
    if not backend:
        raise ProviderDataError("gateway config missing backend")

    source_label = str(payload.get("source_label") or f"gateway_{backend}")

    if backend == "local_file":
        local = payload.get("local_file") or payload
        if not isinstance(local, dict):
            raise ProviderDataError("local_file gateway config must be an object")
        schedule_path = Path(str(local.get("schedule_path") or "data/live_inputs/today_races.json"))
        odds_dir = Path(str(local.get("odds_dir") or "data/live_inputs/odds"))
        results_dir = Path(str(local.get("results_dir") or "data/live_inputs/results"))
        provider = LocalFileProvider(
            schedule_path=schedule_path,
            odds_dir=odds_dir,
            results_dir=results_dir,
            snapshot_at_utc=_optional_datetime(local, "snapshot_at_utc"),
            result_time_utc=_optional_datetime(local, "result_time_utc"),
        )
        return provider, backend, source_label

    if backend in {"contract_api", "approved_api"}:
        raise ProviderUnavailableError(
            f"{backend} gateway backend is reserved for an approved adapter and is not implemented"
        )

    raise ProviderDataError(f"unsupported gateway backend: {backend}")


def _schedule_payload(rows: list[RaceSchedule], *, source_label: str) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in rows:
        item = asdict(row)
        item["race_start_at_utc"] = _utc_iso(row.race_start_at_utc)
        item["source"] = source_label
        payload.append(item)
    return payload


def _odds_payload(rows: list[OddsRow], *, source_label: str) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in rows:
        item = asdict(row)
        item["snapshot_at_utc"] = _utc_iso(row.snapshot_at_utc)
        item["source"] = source_label
        payload.append({key: value for key, value in item.items() if value is not None})
    return payload


def _results_payload(rows: list[ResultRow], *, source_label: str) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in rows:
        item = asdict(row)
        item["result_time_utc"] = _utc_iso(row.result_time_utc)
        item["source"] = source_label
        payload.append({key: value for key, value in item.items() if value is not None})
    return payload


def _provider_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProviderUnavailableError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ProviderDataError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def create_app(*, provider: DataProvider, backend: str, source_label: str) -> FastAPI:
    app = FastAPI(title="Keiba AI Real Data Gateway", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "backend": backend, "source": source_label}

    @app.get("/schedule")
    def schedule(target_date: str = Query(..., description="YYYY-MM-DD")) -> dict[str, list[dict[str, Any]]]:
        try:
            return {
                "races": _schedule_payload(
                    provider.list_today_races(_parse_date(target_date)),
                    source_label=source_label,
                )
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise _provider_error(exc) from exc

    @app.get("/odds/{race_id}")
    def odds(race_id: str) -> dict[str, list[dict[str, Any]]]:
        try:
            return {"odds": _odds_payload(provider.fetch_odds(race_id), source_label=source_label)}
        except HTTPException:
            raise
        except Exception as exc:
            raise _provider_error(exc) from exc

    @app.get("/results/{race_id}")
    def results(race_id: str) -> dict[str, list[dict[str, Any]]]:
        try:
            return {
                "results": _results_payload(
                    provider.fetch_race_result(race_id),
                    source_label=source_label,
                )
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise _provider_error(exc) from exc

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve approved real-data inputs through the generic HTTP provider schema"
    )
    parser.add_argument("--config", default="config/real_data_gateway.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    provider, backend, source_label = build_provider_from_gateway_config(Path(args.config))
    app = create_app(provider=provider, backend=backend, source_label=source_label)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
