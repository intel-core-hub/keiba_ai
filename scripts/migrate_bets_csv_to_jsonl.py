"""
Migrate existing logs/bets.csv into logs/decisions.jsonl using the same
canonical JSON + SHA256 chaining used by BetExecutor._append_jsonl_event.

Usage:
    python scripts/migrate_bets_csv_to_jsonl.py --csv logs/bets.csv --jsonl logs/decisions.jsonl
"""
import argparse
import csv
import json
import hashlib
from datetime import datetime
from pathlib import Path


def canonical_hash(record: dict) -> str:
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def migrate(csv_path: Path, jsonl_path: Path):
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    previous_hash = None

    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    with open(jsonl_path, "a", encoding="utf-8") as out:
        for row in rows:
            record = {
                "event": "bet_executed",
                "timestamp": row.get("timestamp") or datetime.utcnow().isoformat(),
                "payload": {k: (v if v != "" else None) for k, v in row.items()},
                "previous_hash": previous_hash,
            }
            entry_hash = canonical_hash(record)
            record["entry_hash"] = entry_hash
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            previous_hash = entry_hash

    print(f"Migrated {len(rows)} rows to {jsonl_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="logs/bets.csv")
    p.add_argument("--jsonl", default="logs/decisions.jsonl")
    args = p.parse_args()
    migrate(Path(args.csv), Path(args.jsonl))
