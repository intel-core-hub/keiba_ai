from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query


def _load_json(path: Path, *, kind: str) -> Any:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"missing {kind} fixture: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"invalid {kind} fixture JSON: {exc}") from exc


def _parse_target_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"target_date must be YYYY-MM-DD: {value}") from exc


def _schedule_rows(schedule_path: Path, target_date: str) -> list[dict[str, Any]]:
    payload = _load_json(schedule_path, kind="schedule")
    if not isinstance(payload, list):
        raise HTTPException(status_code=500, detail="schedule fixture must be a list")

    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise HTTPException(status_code=500, detail="schedule row must be an object")
        race_start = str(item.get("race_start_at_utc") or "")
        if not race_start:
            raise HTTPException(status_code=500, detail="schedule row missing race_start_at_utc")
        try:
            race_date = datetime.fromisoformat(race_start.replace("Z", "+00:00")).date().isoformat()
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=f"invalid race_start_at_utc: {race_start}") from exc
        if race_date != target_date:
            continue
        row = dict(item)
        row.setdefault("source", "mock_api")
        rows.append(row)
    return rows


def _fixture_rows(path: Path, *, kind: str) -> list[dict[str, Any]]:
    payload = _load_json(path, kind=kind)
    if not isinstance(payload, list):
        raise HTTPException(status_code=500, detail=f"{kind} fixture must be a list")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise HTTPException(status_code=500, detail=f"{kind} row must be an object")
        row = dict(item)
        row.setdefault("source", "mock_api")
        rows.append(row)
    return rows


def create_app(*, schedule_path: Path, odds_dir: Path, results_dir: Path) -> FastAPI:
    app = FastAPI(title="Keiba AI Mock Real Data Provider", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/schedule")
    def schedule(target_date: str = Query(..., description="YYYY-MM-DD")) -> dict[str, list[dict[str, Any]]]:
        normalized_date = _parse_target_date(target_date)
        return {"races": _schedule_rows(schedule_path, normalized_date)}

    @app.get("/odds/{race_id}")
    def odds(race_id: str) -> dict[str, list[dict[str, Any]]]:
        return {"odds": _fixture_rows(odds_dir / f"{race_id}.json", kind="odds")}

    @app.get("/results/{race_id}")
    def results(race_id: str) -> dict[str, list[dict[str, Any]]]:
        return {"results": _fixture_rows(results_dir / f"{race_id}.json", kind="results")}

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve mock schedule / odds / result endpoints for HTTP provider dry-runs")
    parser.add_argument("--data-root", default="data/live_inputs/mock_server")
    parser.add_argument("--schedule", default=None, help="override schedule fixture path")
    parser.add_argument("--odds-dir", default=None, help="override odds fixture directory")
    parser.add_argument("--results-dir", default=None, help="override results fixture directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_root = Path(args.data_root)
    schedule_path = Path(args.schedule) if args.schedule else data_root / "today_races.json"
    odds_dir = Path(args.odds_dir) if args.odds_dir else data_root / "odds"
    results_dir = Path(args.results_dir) if args.results_dir else data_root / "results"

    app = create_app(schedule_path=schedule_path, odds_dir=odds_dir, results_dir=results_dir)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
