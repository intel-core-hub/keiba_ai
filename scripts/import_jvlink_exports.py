from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.import_approved_real_data import import_approved_real_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import approved JV-Link exports into data/live_inputs")
    parser.add_argument("--schedule-input", required=True)
    parser.add_argument("--odds-input", required=True)
    parser.add_argument("--results-input", required=True)
    parser.add_argument("--output-root", default="data/live_inputs")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--min-races", type=int, default=1)
    parser.add_argument("--min-horses-per-race", type=int, default=2)
    parser.add_argument("--status", default="reports/data_collection/import_jvlink_exports_status.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = import_approved_real_data(
            schedule_input=Path(args.schedule_input),
            odds_input=Path(args.odds_input),
            results_input=Path(args.results_input),
            output_root=Path(args.output_root),
            source="jvlink_export",
            clean=args.clean,
            min_races=args.min_races,
            min_horses_per_race=args.min_horses_per_race,
        )
    except Exception as exc:
        report = {"passed": False, "error": str(exc), "source": "jvlink_export"}
        status_path = Path(args.status)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1

    status_path = Path(args.status)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
