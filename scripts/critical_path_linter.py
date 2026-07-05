#!/usr/bin/env python3
"""Lint production critical-path code for forbidden runtime operations."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

CRITICAL_PATH_FILES = (
    "core/low_latency_execution.py",
    "core/betting/decision_engine.py",
    "core/betting/risk_clamp.py",
    "core/execution/bet_executor.py",
)

CRITICAL_FUNCTIONS = {
    "execute_critical_path",
    "decide_close_race",
    "evaluate_candidate",
    "execute_bet",
    "_execute_real_vote",
}

SUBMIT_CALLS = {
    "place_bet_async",
    "_execute_real_vote",
    "execute_vote",
    "place_bet",
    "vote",
    "submit_vote",
    "submit_bet",
}

OFFLINE_PARTS = {"research", "scripts", "tests", "dashboard", "tools"}

IMPORT_PATTERNS = (
    (re.compile(r"(^|\s)import\s+pandas\b"), "pandas import"),
    (re.compile(r"(^|\s)from\s+pandas\b"), "pandas import"),
)

SOURCE_PATTERNS = (
    (re.compile(r"\bpandas\.DataFrame\b|\bpd\.DataFrame\b|\bDataFrame\b"), "DataFrame usage"),
    (re.compile(r"\bread_csv\s*\("), "read_csv usage"),
    (re.compile(r"\bto_csv\s*\("), "to_csv usage"),
    (re.compile(r"\bpickle\.load\s*\("), "pickle.load usage"),
    (re.compile(r"\bjoblib\.load\s*\("), "joblib.load usage"),
    (re.compile(r"\b(?:time\.)?sleep\s*\("), "sleep usage"),
    (re.compile(r"\bmodel\.fit\s*\("), "model.fit usage"),
    (re.compile(r"\bcalibrator\.fit\s*\("), "calibrator.fit usage"),
    (re.compile(r"\basyncio\.create_task\s*\("), "hidden async task creation"),
    (re.compile(r"\bif\s+(?:not\s+)?[^\n]*\.can_bet\s*\("), "RiskClamp bypass: can_bet final permission"),
    (re.compile(r"\bif\s+[^\n]*\.risk_multiplier\s*\(\s*\)\s*<=\s*0"), "RiskClamp bypass: risk_multiplier final permission"),
    (re.compile(r"\bif\s+(?:not\s+)?[^\n]*\.max_bet_size\s*\("), "RiskClamp bypass: max_bet_size final permission"),
    (re.compile(r"\.get\s*\(\s*['\"]should_bet['\"]"), "RiskClamp bypass: should_bet final permission"),
    (re.compile(r"\[\s*['\"]should_bet['\"]\s*\]"), "RiskClamp bypass: should_bet final permission"),
    (re.compile(r"\bopen\s*\([^)]*[, ]['\"][wa][+]?['\"]"), "blocking file write"),
    (re.compile(r"\.write_text\s*\("), "blocking file write"),
    (re.compile(r"\.write_bytes\s*\("), "blocking file write"),
    (re.compile(r"\bjson\.load\s*\("), "full JSON load"),
)

REQUESTS_CALL = re.compile(r"\brequests\.\w+\s*\((?P<args>[^)]*)\)")


def critical_files(root: Path) -> list[Path]:
    return [root / raw for raw in CRITICAL_PATH_FILES if (root / raw).exists()]


def _line_for_node(src: str, node: ast.AST) -> str:
    lines = src.splitlines()
    if getattr(node, "lineno", None) is None:
        return ""
    return lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""


def _scan_imports(path: Path, src: str) -> list[tuple[str, str]]:
    violations = []
    for line_no, line in enumerate(src.splitlines(), start=1):
        for pattern, desc in IMPORT_PATTERNS:
            if pattern.search(line):
                violations.append((str(path), f"{desc}:line {line_no}"))
    return violations


def _scan_text(path: Path, src: str, start: int, end: int) -> list[tuple[str, str]]:
    segment = "\n".join(src.splitlines()[start - 1 : end])
    violations = []
    for pattern, desc in SOURCE_PATTERNS:
        match = pattern.search(segment)
        if match:
            line = start + segment[: match.start()].count("\n")
            violations.append((str(path), f"{desc}:line {line}"))

    for match in REQUESTS_CALL.finditer(segment):
        if "timeout=" not in match.group("args"):
            line = start + segment[: match.start()].count("\n")
            violations.append((str(path), f"requests without timeout:line {line}"))

    return violations


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_risk_clamp_evaluate_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "evaluate"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "risk_clamp"
    )


def _assigned_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for item in target.elts:
            names.update(_assigned_names(item))
        return names
    return set()


def _assignment_targets(stmt: ast.stmt) -> set[str]:
    if isinstance(stmt, ast.Assign):
        names: set[str] = set()
        for target in stmt.targets:
            names.update(_assigned_names(target))
        return names
    if isinstance(stmt, ast.AnnAssign):
        return _assigned_names(stmt.target)
    if isinstance(stmt, ast.AugAssign):
        return _assigned_names(stmt.target)
    return set()


def _has_return(statements: list[ast.stmt]) -> bool:
    return any(isinstance(node, ast.Return) for statement in statements for node in ast.walk(statement))


def _is_not_name_attr(test: ast.AST, name: str, attr: str) -> bool:
    return (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Attribute)
        and test.operand.attr == attr
        and isinstance(test.operand.value, ast.Name)
        and test.operand.value.id == name
    )


def _is_not_dict_get(test: ast.AST, name: str, key: str) -> bool:
    if not isinstance(test, ast.UnaryOp) or not isinstance(test.op, ast.Not):
        return False
    call = test.operand
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    if (
        not isinstance(func, ast.Attribute)
        or func.attr != "get"
        or not isinstance(func.value, ast.Name)
        or func.value.id != name
        or not call.args
    ):
        return False
    first = call.args[0]
    return isinstance(first, ast.Constant) and first.value == key


def _is_guard_if(stmt: ast.stmt, function_name: str, risk_result_vars: set[str]) -> bool:
    if not isinstance(stmt, ast.If) or not _has_return(stmt.body):
        return False
    for name in risk_result_vars:
        if _is_not_name_attr(stmt.test, name, "allowed"):
            return True
    if function_name == "execute_critical_path" and _is_not_dict_get(stmt.test, "bet_decision", "allowed"):
        return True
    if function_name == "_execute_real_vote" and _is_not_dict_get(stmt.test, "bet_info", "risk_clamp_allowed"):
        return True
    return False


def _is_submit_expr(node: ast.AST, submit_aliases: set[str]) -> bool:
    name = _call_name(node)
    return bool(name in SUBMIT_CALLS or name in submit_aliases)


def _value_is_submit_alias(value: ast.AST, submit_aliases: set[str]) -> bool:
    return _is_submit_expr(value, submit_aliases)


def _collect_submit_aliases(stmt: ast.stmt, submit_aliases: set[str]) -> None:
    value: ast.AST | None = None
    targets: set[str] = set()
    if isinstance(stmt, ast.Assign):
        value = stmt.value
        for target in stmt.targets:
            targets.update(_assigned_names(target))
    elif isinstance(stmt, ast.AnnAssign):
        value = stmt.value
        targets.update(_assigned_names(stmt.target))

    if value is None or not targets:
        return
    for target in targets:
        if _value_is_submit_alias(value, submit_aliases):
            submit_aliases.add(target)
        else:
            submit_aliases.discard(target)


def _collect_risk_result_vars(stmt: ast.stmt, risk_result_vars: set[str]) -> None:
    value: ast.AST | None = None
    targets: set[str] = set()
    if isinstance(stmt, ast.Assign):
        value = stmt.value
        for target in stmt.targets:
            targets.update(_assigned_names(target))
    elif isinstance(stmt, ast.AnnAssign):
        value = stmt.value
        targets.update(_assigned_names(stmt.target))

    if value is None or not targets:
        return
    for target in targets:
        if _is_risk_clamp_evaluate_call(value):
            risk_result_vars.add(target)
        else:
            risk_result_vars.discard(target)


def _iter_child_statements(stmt: ast.stmt) -> list[list[ast.stmt]]:
    blocks: list[list[ast.stmt]] = []
    for field_name in ("body", "orelse", "finalbody"):
        value = getattr(stmt, field_name, None)
        if isinstance(value, list):
            blocks.append(value)
    handlers = getattr(stmt, "handlers", None)
    if isinstance(handlers, list):
        for handler in handlers:
            body = getattr(handler, "body", None)
            if isinstance(body, list):
                blocks.append(body)
    return blocks


def _statement_expressions(stmt: ast.stmt) -> list[ast.AST]:
    if isinstance(stmt, ast.Expr):
        return [stmt.value]
    if isinstance(stmt, ast.Assign):
        return [stmt.value]
    if isinstance(stmt, ast.AnnAssign):
        return [stmt.value] if stmt.value is not None else []
    if isinstance(stmt, ast.AugAssign):
        return [stmt.value]
    if isinstance(stmt, ast.Return):
        return [stmt.value] if stmt.value is not None else []
    if isinstance(stmt, ast.If):
        return [stmt.test]
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        return [stmt.iter]
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return [item.context_expr for item in stmt.items]
    if isinstance(stmt, ast.Raise):
        values = []
        if stmt.exc is not None:
            values.append(stmt.exc)
        if stmt.cause is not None:
            values.append(stmt.cause)
        return values
    if isinstance(stmt, ast.Assert):
        values = [stmt.test]
        if stmt.msg is not None:
            values.append(stmt.msg)
        return values
    return []


def _submit_calls_in_stmt(stmt: ast.stmt, submit_aliases: set[str]) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for expression in _statement_expressions(stmt):
        for node in ast.walk(expression):
            if isinstance(node, ast.Call) and _is_submit_expr(node.func, submit_aliases):
                calls.append(node)
    return calls


def _scan_submit_guards(
    path: Path,
    src: str,
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[str, str]]:
    violations = []

    def scan_statements(
        statements: list[ast.stmt],
        *,
        guard_proven: bool,
        risk_result_vars: set[str],
        submit_aliases: set[str],
    ) -> None:
        current_guard = guard_proven
        current_risk_vars = set(risk_result_vars)
        current_aliases = set(submit_aliases)

        for stmt in statements:
            for call in _submit_calls_in_stmt(stmt, current_aliases):
                if not current_guard:
                    line_no = getattr(call, "lineno", getattr(function_node, "lineno", 1))
                    violations.append((
                        str(path),
                        f"RiskClamp bypass: submit without RiskClamp guard:line {line_no}",
                    ))

            child_guard = current_guard
            if _is_guard_if(stmt, function_node.name, current_risk_vars):
                child_guard = False
            for child_block in _iter_child_statements(stmt):
                scan_statements(
                    child_block,
                    guard_proven=child_guard,
                    risk_result_vars=current_risk_vars,
                    submit_aliases=current_aliases,
                )

            _collect_submit_aliases(stmt, current_aliases)
            _collect_risk_result_vars(stmt, current_risk_vars)
            if _is_guard_if(stmt, function_node.name, current_risk_vars):
                current_guard = True

            for name in _assignment_targets(stmt):
                if name not in current_risk_vars:
                    continue
                if not (
                    isinstance(stmt, (ast.Assign, ast.AnnAssign))
                    and _is_risk_clamp_evaluate_call(getattr(stmt, "value", None))
                ):
                    current_risk_vars.discard(name)

    scan_statements(
        function_node.body,
        guard_proven=False,
        risk_result_vars=set(),
        submit_aliases=set(),
    )
    return violations


def scan_file(path: Path) -> list[tuple[str, str]]:
    if OFFLINE_PARTS.intersection(path.parts):
        return []
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:
        return [(str(path), f"read-error:{exc}")]

    violations = _scan_imports(path, src)
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        violations.append((str(path), f"parse-error:{exc.msg}:line {exc.lineno}"))
        return violations

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name not in CRITICAL_FUNCTIONS:
                continue
            end = getattr(node, "end_lineno", node.lineno)
            violations.extend(_scan_text(path, src, node.lineno, end))
            violations.extend(_scan_submit_guards(path, src, node))
    return violations


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    all_violations: list[tuple[str, str]] = []
    for path in critical_files(root):
        all_violations.extend(scan_file(path))

    if all_violations:
        print("Critical-path linter violations detected:")
        for path, desc in all_violations:
            print(f" - {path}: {desc}")
        return 1

    print("No critical-path violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
