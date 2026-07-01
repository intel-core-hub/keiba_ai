from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(payload: Any, *, field: str, path: Path) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get(field) if field in payload else [payload]
    else:
        raise ValueError(f"{path}: expected list or object")
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected {field} list")
    return rows


def _float(value: Any, *, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric: {value}") from exc


def _bool_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "win", "winner"}:
        return 1
    if text in {"0", "false", "no", "n", "lose", "lost", ""}:
        return 0
    raise ValueError(f"is_win must be boolean-like: {value}")


def build_pre_contract_shadow_input(
    *,
    schedule: Path,
    odds_dir: Path,
    results_dir: Path,
    output: Path,
    status: Path | None = None,
) -> dict[str, Any]:
    schedule_rows = _rows(_load_json(schedule), field="schedule", path=schedule)
    race_ids = [str(row.get("race_id") or "").strip() for row in schedule_rows]
    race_ids = [race_id for race_id in race_ids if race_id]
    if not race_ids:
        raise ValueError("schedule has no race_id values")

    output_rows: list[dict[str, Any]] = []
    for race_id in race_ids:
        odds_path = odds_dir / f"{race_id}.json"
        result_path = results_dir / f"{race_id}.json"
        odds_rows = _rows(_load_json(odds_path), field="odds", path=odds_path)
        result_rows = _rows(_load_json(result_path), field="results", path=result_path)
        result_by_horse = {
            str(row.get("horse_id") or row.get("selection_id") or "").strip(): row
            for row in result_rows
        }
        sorted_odds = sorted(
            odds_rows,
            key=lambda row: (
                _float(row.get("odds"), field="odds"),
                str(row.get("horse_id") or row.get("selection_id") or ""),
            ),
        )
        field_size = len(sorted_odds)
        rank_by_horse = {
            str(row.get("horse_id") or row.get("selection_id") or "").strip(): rank
            for rank, row in enumerate(sorted_odds, start=1)
        }
        for row in odds_rows:
            horse_id = str(row.get("horse_id") or row.get("selection_id") or "").strip()
            if not horse_id:
                raise ValueError(f"{odds_path}: odds row missing horse_id")
            odds = _float(row.get("odds"), field="odds")
            favorite_rank = rank_by_horse[horse_id]
            market_support = round(min(0.95, max(0.02, 1.0 / odds)), 6)
            rank_score = round(1.0 - ((favorite_rank - 1) / max(field_size - 1, 1)), 6)
            result = result_by_horse.get(horse_id, {})
            output_rows.append(
                {
                    "race_id": race_id,
                    "selection": horse_id,
                    "horse_id": horse_id,
                    "odds": odds,
                    "hit": _bool_int(result.get("is_win", False)),
                    "features": json.dumps(
                        {
                            "field_size": field_size,
                            "favorite_rank": favorite_rank,
                            "market_support": market_support,
                            "rank_score": rank_score,
                            "recent_form_score": 0.5,
                            "consistency_index": 0.5,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "odds_snapshot_hash": f"{race_id}:{horse_id}:sandbox_odds",
                    "feature_snapshot_hash": f"{race_id}:{horse_id}:sandbox_features",
                }
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "race_id",
        "selection",
        "horse_id",
        "odds",
        "hit",
        "features",
        "odds_snapshot_hash",
        "feature_snapshot_hash",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    report = {
        "passed": True,
        "evidence_eligible": False,
        "schedule": str(schedule),
        "odds_dir": str(odds_dir),
        "results_dir": str(results_dir),
        "output": str(output),
        "race_count": len(race_ids),
        "row_count": len(output_rows),
        "warning": "Pre-contract shadow input is sandbox-only and must not be used as Stage 4 evidence.",
    }
    if status is not None:
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build sandbox-only shadow input from pre-contract live_inputs")
    parser.add_argument("--schedule", default="reports/data_collection/pre_contract_sandbox/live_inputs/today_races.json")
    parser.add_argument("--odds-dir", default="reports/data_collection/pre_contract_sandbox/live_inputs/odds")
    parser.add_argument("--results-dir", default="reports/data_collection/pre_contract_sandbox/live_inputs/results")
    parser.add_argument("--output", default="reports/data_collection/pre_contract_sandbox/shadow_input.csv")
    parser.add_argument("--status", default="reports/data_collection/pre_contract_sandbox_shadow_input_status.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = build_pre_contract_shadow_input(
            schedule=Path(args.schedule),
            odds_dir=Path(args.odds_dir),
            results_dir=Path(args.results_dir),
            output=Path(args.output),
            status=Path(args.status),
        )
    except Exception as exc:
        report = {"passed": False, "evidence_eligible": False, "error": str(exc)}
        status_path = Path(args.status)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
