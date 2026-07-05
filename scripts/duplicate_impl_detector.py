#!/usr/bin/env python3
"""Detect duplicate production implementations across runtime-owned files."""
import ast
import sys
from collections import defaultdict
from pathlib import Path

RUNTIME_TARGETS = (
    "core/low_latency_execution.py",
    "core/betting",
    "core/execution",
    "core/replay",
    "production",
    "execution",
    "infrastructure/api_server.py",
    "schemas",
)

UNIQUE_RUNTIME_CLASSES = {"DecisionEngine", "RegimeDetector"}


def collect_defs(path: Path):
    try:
        src = path.read_text(encoding="utf8")
    except Exception:
        return []
    try:
        tree = ast.parse(src)
    except Exception:
        return []
    names = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.name not in UNIQUE_RUNTIME_CLASSES:
                continue
            names.append(node.name)
    return names


def runtime_files(root: Path):
    files = set()
    for raw in RUNTIME_TARGETS:
        target = root / raw
        if target.is_file():
            files.add(target)
        elif target.is_dir():
            files.update(
                p
                for p in target.rglob("*.py")
                if "__pycache__" not in p.parts and ".venv" not in p.parts
            )
    return sorted(files)


def find_duplicates(root: Path):
    py_files = runtime_files(root)
    index = defaultdict(list)
    for p in py_files:
        defs = collect_defs(p)
        for name in defs:
            index[name].append(str(p))

    return {k: v for k, v in index.items() if len(v) > 1}


def main():
    root = Path(__file__).resolve().parents[1]
    duplicates = find_duplicates(root)
    if duplicates:
        print("Duplicate implementations detected:")
        for name, files in duplicates.items():
            print(f" - {name}:\n")
            for f in files:
                print(f"    {f}")
        sys.exit(1)
    else:
        print("No duplicate top-level implementations found.")


if __name__ == "__main__":
    main()
