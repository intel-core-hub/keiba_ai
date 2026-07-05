from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from scripts.import_approved_real_data import ALLOWED_SOURCES, BANNED_SOURCE_MARKERS


REQUIRED_FILES = {
    "schedule": {
        "path": "schedule.csv",
        "required_columns": {"race_id", "race_start_at_utc"},
        "recommended_columns": {"venue", "race_number", "source"},
    },
    "odds": {
        "path": "odds.csv",
        "required_columns": {"race_id", "horse_id", "odds", "snapshot_at_utc"},
        "recommended_columns": {"source"},
    },
    "results": {
        "path": "results.csv",
        "required_columns": {
            "race_id",
            "horse_id",
            "finish_position",
            "is_win",
            "win_payout",
            "result_time_utc",
        },
        "recommended_columns": {"source"},
    },
}


def _csv_summary(path: Path) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [str(name).strip() for name in (reader.fieldnames or [])]
        rows = [row for row in reader]
    source_values = sorted({str(row.get("source") or "").strip().lower() for row in rows if row.get("source")})
    invalid_sources = [
        source
        for source in source_values
        if source not in ALLOWED_SOURCES or any(marker in source for marker in BANNED_SOURCE_MARKERS)
    ]
    return {
        "columns": fieldnames,
        "row_count": len(rows),
        "source_values": source_values,
        "invalid_sources": invalid_sources,
    }


def check_approved_exports_ready(root: Path) -> dict[str, Any]:
    files: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []

    for name, spec in REQUIRED_FILES.items():
        path = root / str(spec["path"])
        required_columns = set(spec["required_columns"])
        recommended_columns = set(spec["recommended_columns"])
        item: dict[str, Any] = {
            "path": str(path),
            "exists": path.exists(),
            "required_columns": sorted(required_columns),
            "recommended_columns": sorted(recommended_columns),
        }
        if not path.exists():
            errors.append(f"missing required export: {path}")
            files[name] = item
            continue
        summary = _csv_summary(path)
        columns = set(summary["columns"])
        missing_required = sorted(required_columns - columns)
        missing_recommended = sorted(recommended_columns - columns)
        item.update(summary)
        item["missing_required_columns"] = missing_required
        item["missing_recommended_columns"] = missing_recommended
        if missing_required:
            errors.append(f"{path}: missing required columns {missing_required}")
        if missing_recommended:
            warnings.append(f"{path}: missing recommended columns {missing_recommended}")
        if summary["row_count"] == 0:
            warnings.append(f"{path}: no data rows yet")
        for source in summary["invalid_sources"]:
            errors.append(f"{path}: invalid source value {source!r}")
        files[name] = item

    ready_for_import = not errors and all(files[name].get("row_count", 0) > 0 for name in REQUIRED_FILES)
    return {
        "passed": not errors,
        "ready_for_import": ready_for_import,
        "root": str(root),
        "files": files,
        "errors": errors,
        "warnings": warnings,
        "next_step": (
            "Run scripts.import_jvlink_exports or scripts.import_approved_real_data."
            if ready_for_import
            else "Place approved schedule.csv, odds.csv, and results.csv in approved_exports/."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check whether approved real-data exports are ready to import")
    parser.add_argument("--root", default="approved_exports")
    parser.add_argument("--status", default="reports/data_collection/approved_exports_pre_contract_status.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = check_approved_exports_ready(Path(args.root))
    status_path = Path(args.status)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
