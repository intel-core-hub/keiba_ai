"""
Verify integrity of logs/decisions.jsonl by checking canonical JSON -> SHA256 chain.

Usage:
    python scripts/verify_bets_jsonl.py --jsonl logs/decisions.jsonl
"""
import argparse
import json
import hashlib
from pathlib import Path


def canonical_hash(record: dict) -> str:
    # compute hash of record without entry_hash
    r = {k: record[k] for k in sorted(record.keys()) if k != "entry_hash"}
    canonical = json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify(jsonl_path: Path) -> int:
    if not jsonl_path.exists():
        raise SystemExit(f"JSONL not found: {jsonl_path}")

    errors = 0
    prev = None
    idx = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            idx += 1
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception as exc:
                print(f"Line {idx}: invalid JSON: {exc}")
                errors += 1
                continue

            entry_hash = obj.get("entry_hash")
            if obj.get("previous_hash") != prev:
                print(f"Line {idx}: previous_hash mismatch (expected {prev} got {obj.get('previous_hash')})")
                errors += 1

            calc = canonical_hash(obj)
            if calc != entry_hash:
                print(f"Line {idx}: entry_hash mismatch (calc {calc} != stored {entry_hash})")
                errors += 1

            prev = entry_hash

    return errors


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--jsonl", default="logs/decisions.jsonl")
    args = p.parse_args()
    errs = verify(Path(args.jsonl))
    if errs:
        print(f"Verification completed: {errs} errors")
    else:
        print("Verification OK: no errors found")
