from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.replay.historical_snapshot_loader import HistoricalSnapshotLoader
from core.replay.replay_engine import ReplayEngine
from scripts.derive_bets_csv_from_decisions import derive as derive_bets_csv
from scripts.shadow_run_from_file import run_shadow_file


JST = ZoneInfo("Asia/Tokyo")
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://en.netkeiba.com/"}


def _field_rows(race_id: str) -> dict[str, dict[str, object]]:
    html = requests.get(
        f"https://en.netkeiba.com/race/shutuba.html?race_id={race_id}",
        headers=HEADERS,
        timeout=20,
    ).text
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.Shutuba_Table")
    rows: dict[str, dict[str, object]] = {}
    if table is None:
        return rows
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if len(cells) < 7 or cells[0] == "BK":
            continue
        try:
            horse_no = int(cells[1])
        except ValueError:
            continue
        age_match = re.match(r"(\d+)", cells[4])
        rows[f"{horse_no:02d}"] = {
            "horse_number": horse_no,
            "horse_name": cells[3],
            "age": int(age_match.group(1)) if age_match else "",
            "weight_carried": float(cells[5]) if re.match(r"^\d+(\.\d+)?$", cells[5]) else "",
        }
    return rows


def _win_odds(race_id: str) -> tuple[str | None, str | None, dict[str, list[str]]]:
    params = {
        "pid": "api_get_jra_odds",
        "input": "UTF-8",
        "output": "json",
        "race_id": race_id,
        "type": "1",
        "action": "init",
        "sort": "odds",
        "compress": "0",
    }
    response = requests.get(
        "https://en.netkeiba.com/race/api_get_jra_odds.html",
        params=params,
        headers={**HEADERS, "Referer": f"https://en.netkeiba.com/race/odds_view.html?race_id={race_id}"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", {})
    return payload.get("status"), data.get("official_datetime"), data.get("odds", {}).get("1", {})


def write_input_csv(race: dict[str, str], output_path: Path) -> dict[str, object]:
    now = datetime.now(JST)
    field = _field_rows(race["race_id"])
    status, official_dt, odds_map = _win_odds(race["race_id"])
    field_size = len(odds_map) or len(field)
    rows: list[dict[str, object]] = []
    for horse_no, payload in sorted(odds_map.items(), key=lambda kv: int(kv[0])):
        odds = float(payload[0])
        favorite_rank = int(payload[2]) if len(payload) > 2 and str(payload[2]).isdigit() else field_size
        field_row = field.get(horse_no, {})
        features = {
            "rank_score": round(1.0 - ((favorite_rank - 1) / max(field_size - 1, 1)), 6),
            "recent_form_score": 0.5,
            "market_support": round(min(0.95, max(0.02, 1.0 / odds)), 6),
            "consistency_index": 0.5,
            "favorite_rank": favorite_rank,
            "field_size": field_size,
        }
        if field_row.get("age") != "":
            features["age"] = field_row.get("age")
        if field_row.get("weight_carried") != "":
            features["weight_carried"] = field_row.get("weight_carried")
        snapshot_basis = f"{race['race_id']}:{horse_no}:{official_dt}:{odds}:{favorite_rank}:{now.isoformat()}"
        rows.append(
            {
                "race_id": race["race_id"],
                "venue": race["venue"],
                "race_no": race["race_no"],
                "race_name": race["race_name"],
                "race_time": race["race_time"],
                "selection": str(int(horse_no)),
                "horse_id": str(int(horse_no)),
                "horse_number": str(int(horse_no)),
                "horse_name": field_row.get("horse_name", ""),
                "odds": odds,
                "features": json.dumps(features, separators=(",", ":"), sort_keys=True),
                "odds_snapshot_hash": hashlib.sha256(snapshot_basis.encode()).hexdigest(),
                "feature_snapshot_hash": hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest(),
                "odds_status": status,
                "odds_official_datetime": official_dt,
                "source_url": f"https://en.netkeiba.com/race/odds_view.html?race_id={race['race_id']}",
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "race_id",
        "venue",
        "race_no",
        "race_name",
        "race_time",
        "selection",
        "horse_id",
        "horse_number",
        "horse_name",
        "odds",
        "features",
        "odds_snapshot_hash",
        "feature_snapshot_hash",
        "odds_status",
        "odds_official_datetime",
        "source_url",
    ]
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return {
        "input": str(output_path),
        "rows": len(rows),
        "odds_status": status,
        "odds_official_datetime": official_dt,
        "snapshot_at": now.isoformat(),
    }


def write_order_sheet(input_path: Path, derived_bets: Path, output_path: Path) -> list[dict[str, str]]:
    input_rows = list(csv.DictReader(input_path.open(encoding="utf-8-sig")))
    by_key = {(row["race_id"], row["selection"]): row for row in input_rows}
    bets = list(csv.DictReader(derived_bets.open(encoding="utf-8-sig")))
    min_occurred_at = datetime.fromtimestamp(input_path.stat().st_mtime, tz=timezone.utc) - timedelta(seconds=10)
    orders: list[dict[str, str]] = []
    seen: set[str] = set()
    for bet in bets:
        if bet.get("event_type") != "BetSubmitted":
            continue
        occurred_at_text = bet.get("occurred_at_utc") or ""
        try:
            occurred_at = datetime.fromisoformat(occurred_at_text)
        except ValueError:
            continue
        if occurred_at < min_occurred_at:
            continue
        race_id = bet.get("race_id", "")
        selection = bet.get("selection_id") or bet.get("selection") or ""
        source = by_key.get((race_id, selection))
        if source is None:
            continue
        decision_id = bet.get("decision_id") or f"{race_id}:{selection}"
        if decision_id in seen:
            continue
        seen.add(decision_id)
        orders.append(
            {
                "race_time": source["race_time"],
                "venue": source["venue"],
                "race_no": source["race_no"],
                "race_name": source["race_name"],
                "race_id": race_id,
                "bet_type": "単勝",
                "horse_number": selection,
                "horse_name": source.get("horse_name", ""),
                "odds": bet.get("odds") or source.get("odds", ""),
                "stake": bet.get("stake", ""),
                "execution_status": bet.get("execution_status", ""),
                "shadow_mode": bet.get("shadow_mode", ""),
                "safe_mode": bet.get("safe_mode", ""),
                "decision_id": decision_id,
                "occurred_at_utc": bet.get("occurred_at_utc", ""),
            }
        )
    orders.sort(key=lambda row: (row["race_time"], int(row["horse_number"]) if row["horse_number"].isdigit() else 999))
    lines = [
        f"# JIT Shadow Order Sheet {input_path.stem}",
        "",
        "Status: SHADOW / SAFE only. This is not a live betting instruction.",
        "",
        "| Time | Venue | Race | Type | Horse No | Horse | Odds | Stake |",
        "|---|---|---|---|---:|---|---:|---:|",
    ]
    if orders:
        for order in orders:
            lines.append(
                f"| {order['race_time']} | {order['venue']} | {order['race_no']} {order['race_name']} | "
                f"{order['bet_type']} | {order['horse_number']} | {order['horse_name']} | {order['odds']} | {order['stake']} |"
            )
    else:
        lines.append("| - | - | - | - | - | No shadow candidates | - | - |")
    lines.extend(
        [
            "",
            "Notes:",
            "- Input odds were win odds from netkeiba api_get_jra_odds type=1.",
            "- BetRejected rows with api_status=shadow are expected in SAFE/SHADOW mode; no live order was sent.",
            "- Current runner generates single-selection win candidates only.",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    csv_path = output_path.with_suffix(".csv")
    if orders:
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(orders[0]))
            writer.writeheader()
            writer.writerows(orders)
    return orders


def run_one(race: dict[str, str], args: argparse.Namespace) -> dict[str, object]:
    race_time = datetime.fromisoformat(race["race_time"])
    stamp = race_time.strftime("%Y%m%d_%H%M")
    base = f"jit_shadow_{stamp}_{race['venue'].lower()}_{race['race_no'].lower()}"
    input_path = Path(args.output_dir) / f"{base}.csv"
    order_path = Path(args.output_dir) / f"{base}_order_sheet.md"
    input_summary = write_input_csv(race, input_path)
    run_summary = run_shadow_file(
        input_path,
        Path(args.decision_log),
        Path(args.csv_report),
        settle=False,
    )
    derive_bets_csv(Path(args.decision_log), Path(args.csv_report))
    orders = write_order_sheet(input_path, Path(args.csv_report), order_path)
    replay = ReplayEngine(loader=HistoricalSnapshotLoader()).replay(
        Path(args.decision_log),
        out_report=Path(args.replay_report),
    )
    return {
        "race": race,
        "input": input_summary,
        "shadow": run_summary,
        "orders": orders,
        "order_sheet": str(order_path),
        "replay_summary": replay["summary"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run just-in-time Stage4 shadow checks before race start")
    parser.add_argument("--races-json", default=None, help="JSON array of race objects")
    parser.add_argument("--races-file", default=None, help="Path to a JSON array of race objects")
    parser.add_argument("--minutes-before", type=float, default=3.0)
    parser.add_argument("--output-dir", default="reports/stage4/jit_shadow")
    parser.add_argument("--decision-log", default="logs/decisions.jsonl")
    parser.add_argument("--csv-report", default="derived/bets.csv")
    parser.add_argument("--replay-report", default="reports/stage4/replay_report.json")
    parser.add_argument("--summary", default="reports/stage4/jit_shadow/summary.json")
    parser.add_argument("--no-wait", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.races_file:
        races = json.loads(Path(args.races_file).read_text(encoding="utf-8"))
    elif args.races_json:
        races = json.loads(args.races_json)
    else:
        raise SystemExit("--races-json or --races-file is required")
    reports = []
    for race in sorted(races, key=lambda item: item["race_time"]):
        race_time = datetime.fromisoformat(race["race_time"])
        target_time = race_time - timedelta(minutes=args.minutes_before)
        now = datetime.now(JST)
        if not args.no_wait and now < target_time:
            time.sleep((target_time - now).total_seconds())
        reports.append(run_one(race, args))
        Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary).write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
