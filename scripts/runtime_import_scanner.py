#!/usr/bin/env python3
"""Fail CI when production runtime imports research/offline modules."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

RUNTIME_TARGETS = (
    "core/__init__.py",
    "core/low_latency_execution.py",
    "core/execution",
    "core/betting",
    "core/prediction",
    "core/audit",
    "core/system_orchestrator.py",
    "production",
    "execution",
    "infrastructure/api_server.py",
    "execution/race_runner.py",
    "execution/scheduler.py",
    "main.py",
)

FORBIDDEN_TOP_LEVEL = {
    "research",
    "learning",
    "dashboard",
    "simulation",
    "scripts",
    "tools",
    "validation",
    "reports",
    "gh_artifacts",
}

FORBIDDEN_FRAGMENTS = {
    "auto_evolver",
    "meta_learner",
    "recursive_optimizer",
    "future_synthesis",
    "civilization",
    "self_modifier",
    "autonomous_researcher",
}

CORE_INIT_FORBIDDEN_STRINGS = {
    "__getattr__",
    "RegimeDetector",
    "BetSizer",
    "BankrollManager",
    "DecisionEngine",
    "BetExecutor",
    "SelfDestructSystem",
    "MetaController",
    "import_module",
    "KEIBA_ENABLE_RESEARCH",
}


def _is_under(path: Path, target: Path) -> bool:
    try:
        path.relative_to(target)
        return True
    except ValueError:
        return False


def runtime_files(root: Path) -> list[Path]:
    files: set[Path] = set()
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


def _module_is_forbidden(module: str) -> bool:
    normalized = module.replace("\\", ".").replace("/", ".")
    top = normalized.split(".", 1)[0]
    return top in FORBIDDEN_TOP_LEVEL or any(
        fragment in normalized for fragment in FORBIDDEN_FRAGMENTS
    )


def scan_file(path: Path) -> list[tuple[str, str]]:
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:
        return [(str(path), f"read-error:{exc}")]

    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        return _scan_import_text(path, src, f"parse-fallback:{exc.msg}:line {exc.lineno}")

    violations: list[tuple[str, str]] = []
    if path.as_posix().endswith("core/__init__.py"):
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                violations.append((str(path), "core package marker must not import modules"))
        for token in CORE_INIT_FORBIDDEN_STRINGS:
            if token in src:
                violations.append((str(path), f"core package marker forbidden symbol: {token}"))
        if "__all__: list[str] = []" not in src:
            violations.append((str(path), "core package marker must keep empty __all__"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                if _module_is_forbidden(name.name):
                    violations.append((str(path), f"import {name.name}"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if _module_is_forbidden(node.module):
                violations.append((str(path), f"from {node.module} import ..."))
    return violations


def _scan_import_text(path: Path, src: str, context: str) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    import_line = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))")
    for line_no, line in enumerate(src.splitlines(), start=1):
        match = import_line.match(line)
        if not match:
            continue
        module = match.group(1) or match.group(2)
        if _module_is_forbidden(module):
            violations.append((str(path), f"{context}: {line.strip()} at line {line_no}"))
    return violations


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    all_violations: list[tuple[str, str]] = []
    for path in runtime_files(root):
        all_violations.extend(scan_file(path))

    if all_violations:
        print("Runtime import violations detected:")
        for path, desc in all_violations:
            print(f" - {path}: {desc}")
        return 1

    print("No forbidden runtime imports found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
