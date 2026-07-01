from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.data_sources.base import DataProvider, OddsRow
from core.data_sources.http_provider import build_http_provider_from_yaml
from core.data_sources.local_file_provider import LocalFileProvider, parse_utc_datetime
from core.data_sources.provider_errors import ProviderError


SNAPSHOT_FIELDS = [
    "race_id",
    "horse_id",
    "snapshot_time",
    "odds",
    "source",
    "provider_latency_ms",
    "raw_payload_hash",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _write_error(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"logged_at_utc": _iso_utc(_utc_now()), **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return {
            (row.get("race_id", ""), row.get("horse_id", ""))
            for row in csv.DictReader(handle)
        }


def _append_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SNAPSHOT_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def _row_to_csv(row: OddsRow, *, snapshot_type: str, errors_path: Path) -> dict[str, Any] | None:
    if not row.horse_id:
        _write_error(errors_path, {"step": "collect_market_snapshots", "snapshot_type": snapshot_type, "race_id": row.race_id, "reason": "missing_horse_id"})
        return None
    if row.snapshot_at_utc is None:
        _write_error(errors_path, {"step": "collect_market_snapshots", "snapshot_type": snapshot_type, "race_id": row.race_id, "horse_id": row.horse_id, "reason": "missing_snapshot_time"})
        return None
    if row.odds <= 0:
        _write_error(errors_path, {"step": "collect_market_snapshots", "snapshot_type": snapshot_type, "race_id": row.race_id, "horse_id": row.horse_id, "reason": "invalid_odds", "odds": row.odds})
        return None
    return {
        "race_id": row.race_id,
        "horse_id": row.horse_id,
        "snapshot_time": _iso_utc(row.snapshot_at_utc),
        "odds": row.odds,
        "source": row.source,
        "provider_latency_ms": "" if row.provider_latency_ms is None else round(float(row.provider_latency_ms), 6),
        "raw_payload_hash": row.raw_payload_hash or "",
    }


def _provider(args: argparse.Namespace, now_utc: datetime) -> DataProvider:
    if args.provider == "local_file":
        return LocalFileProvider(
            schedule_path=Path(args.schedule),
            odds_dir=Path(args.odds_dir),
            snapshot_at_utc=now_utc,
        )
    if args.provider == "http":
        config_path = Path(getattr(args, "provider_config", "config/real_data_provider.yaml"))
        return build_http_provider_from_yaml(config_path, observed_at_utc=now_utc)
    raise ValueError(f"unsupported provider: {args.provider}")


def collect_market_snapshots(args: argparse.Namespace) -> dict[str, Any]:
    now_utc = parse_utc_datetime(args.now, field="now") if args.now else _utc_now()
    provider = _provider(args, now_utc)
    errors_path = Path(args.errors)
    outputs = {
        "early": Path(args.early_output),
        "closing": Path(args.closing_output),
    }
    existing = {name: _existing_keys(path) for name, path in outputs.items()}
    pending: dict[str, list[dict[str, Any]]] = {"early": [], "closing": []}
    counts: dict[str, Any] = {
        "races_seen": 0,
        "races_in_window": 0,
        "written": {"early": 0, "closing": 0},
        "skipped_duplicate": {"early": 0, "closing": 0},
        "skipped_out_of_window": 0,
        "invalid_rows": 0,
        "provider_errors": 0,
    }

    races = provider.list_today_races(now_utc.date())
    counts["races_seen"] = len(races)
    for race in races:
        targets: list[str] = []
        minutes_before = (race.race_start_at_utc - now_utc).total_seconds() / 60.0
        if abs(minutes_before - float(args.early_minutes_before)) <= float(args.window_minutes):
            targets.append("early")
        if abs(minutes_before - float(args.closing_minutes_before)) <= float(args.window_minutes):
            targets.append("closing")
        if not targets:
            counts["skipped_out_of_window"] += 1
            continue
        counts["races_in_window"] += 1
        try:
            odds_rows = provider.fetch_odds(race.race_id)
        except ProviderError as exc:
            counts["provider_errors"] += len(targets)
            for target in targets:
                _write_error(errors_path, {"step": "collect_market_snapshots", "snapshot_type": target, "race_id": race.race_id, "reason": "provider_error", "detail": str(exc)})
            continue
        for target in targets:
            for odds in odds_rows:
                csv_row = _row_to_csv(odds, snapshot_type=target, errors_path=errors_path)
                if csv_row is None:
                    counts["invalid_rows"] += 1
                    continue
                key = (csv_row["race_id"], csv_row["horse_id"])
                if key in existing[target]:
                    counts["skipped_duplicate"][target] += 1
                    continue
                existing[target].add(key)
                pending[target].append(csv_row)
                counts["written"][target] += 1

    for target, rows in pending.items():
        _append_csv(outputs[target], rows)

    status = {
        "generated_at_utc": _iso_utc(now_utc),
        "provider": args.provider,
        "passed": counts["provider_errors"] == 0 and counts["invalid_rows"] == 0,
        "counts": counts,
        "outputs": {key: str(value) for key, value in outputs.items()},
        "errors": str(errors_path),
    }
    status_path = Path(args.status)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect real early/closing market snapshots")
    parser.add_argument("--provider", choices=("local_file", "http"), default="local_file")
    parser.add_argument("--provider-config", default="config/real_data_provider.yaml")
    parser.add_argument("--schedule", default="data/live_inputs/today_races.json")
    parser.add_argument("--odds-dir", default="data/live_inputs/odds")
    parser.add_argument("--early-minutes-before", type=float, default=30)
    parser.add_argument("--closing-minutes-before", type=float, default=5)
    parser.add_argument("--window-minutes", type=float, default=3)
    parser.add_argument("--early-output", default="data/market_snapshots/early_odds.csv")
    parser.add_argument("--closing-output", default="data/market_snapshots/closing_odds.csv")
    parser.add_argument("--status", default="reports/data_collection/collection_status.json")
    parser.add_argument("--errors", default="reports/data_collection/collection_errors.jsonl")
    parser.add_argument("--now", default=None, help="UTC ISO8601 override for deterministic runs")
    return parser.parse_args()


def main() -> int:
    status = collect_market_snapshots(parse_args())
    print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
