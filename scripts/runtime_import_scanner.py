#!/usr/bin/env python3
"""Scan the workspace for forbidden runtime imports.

Exit code 0 when clean, 1 when violations found.
"""
import ast
import sys
from pathlib import Path

FORBIDDEN_TOP_LEVEL = (
    "research",
    "experimental",
    "recursive",
    "civilization",
    "memory",
    "future",
    "alignment",
    "autonomous",
    "self_modify",
    "notebooks",
    "training",
)


def scan_file(path: Path):
    try:
        src = path.read_text(encoding="utf8")
    except Exception:
        return []
    try:
        tree = ast.parse(src)
    except Exception:
        return [(str(path), "parse-error")]

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                top = n.name.split(".")[0]
                if top in FORBIDDEN_TOP_LEVEL:
                    violations.append((str(path), f"import {n.name}"))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in FORBIDDEN_TOP_LEVEL:
                    violations.append((str(path), f"from {node.module} import ..."))
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
        print("Runtime import violations detected:")
        for path, desc in all_violations:
            print(f" - {path}: {desc}")
        sys.exit(1)
    else:
        print("No forbidden runtime imports found.")


if __name__ == "__main__":
    main()
