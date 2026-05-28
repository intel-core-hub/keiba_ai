#!/usr/bin/env python3
"""Simple linter to detect forbidden critical-path constructs.

This is intentionally conservative: it looks for well-known risky symbols and patterns
that are forbidden in the critical path (pandas, dataframe, sorting, sync I/O, JSON/CSV writes).
"""
import re
import sys
from pathlib import Path

PATTERNS = [
    (re.compile(r"import\s+pandas"), "pandas import"),
    (re.compile(r"\bDataFrame\b"), "DataFrame usage"),
    (re.compile(r"\.sort_values\(|\.sort\(|\bsorted\("), "sorting operation"),
    (re.compile(r"json\.dump\(|json\.dumps\("), "json serialization"),
    (re.compile(r"csv\.writer\(|csv\.DictWriter\(|pandas\.to_csv\("), "csv write"),
    (re.compile(r"open\(.*[, ]*['\"]w['\"]"), "synchronous file write (open with 'w')"),
    (re.compile(r"requests\.\w+\("), "requests usage (network call)"),
]


def scan_file(path: Path):
    try:
        s = path.read_text(encoding="utf8")
    except Exception:
        return []
    violations = []
    for pat, desc in PATTERNS:
        if pat.search(s):
            violations.append((str(path), desc))
    return violations


def main():
    root = Path(__file__).resolve().parents[1]
    py_files = [p for p in root.rglob("*.py") if "venv" not in p.parts and ".venv" not in p.parts]
    all_violations = []
    for p in py_files:
        v = scan_file(p)
        if v:
            all_violations.extend(v)

    if all_violations:
        print("Critical-path linter violations detected:")
        for path, desc in all_violations:
            print(f" - {path}: {desc}")
        sys.exit(1)
    else:
        print("No critical-path violations found.")


if __name__ == "__main__":
    main()
