#!/usr/bin/env python3
"""Detect duplicate top-level class or function names across files.

This is a lightweight detector: it flags identical top-level symbol names defined in
multiple files which may indicate duplicate implementations.
"""
import ast
import sys
from collections import defaultdict
from pathlib import Path


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
        if isinstance(node, ast.ClassDef) or isinstance(node, ast.FunctionDef):
            names.append(node.name)
    return names


def main():
    root = Path(__file__).resolve().parents[1]
    py_files = [p for p in root.rglob("*.py") if "venv" not in p.parts and ".venv" not in p.parts]
    index = defaultdict(list)
    for p in py_files:
        defs = collect_defs(p)
        for name in defs:
            index[name].append(str(p))

    duplicates = {k: v for k, v in index.items() if len(v) > 1}
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
