from __future__ import annotations

import ast
import csv
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTDIR = ROOT / "reports" / "architecture"

PRODUCTION_PREFIXES = (
    "core.prediction",
    "core.betting",
    "core.execution",
    "core.market",
    "core.security",
    "dashboard",
    "execution",
    "infrastructure",
    "simulation",
    "validation",
)

PRODUCTION_MODULES = {
    "main",
    "core.auto_operator",
    "core.system_orchestrator",
    "dashboard.app",
    "dashboard.control_panel",
    "execution.phase2_loop",
    "infrastructure.api_server",
    "infrastructure.orchestrator",
    "simulation.live_simulation",
}

RESEARCH_PREFIXES = (
    "core.adaptation",
    "core.alignment",
    "core.cognition",
    "core.civilization",
    "core.evolution",
    "core.future",
    "core.governance",
    "core.immune",
    "core.memory",
    "learning",
    "meta",
    "strategies",
)

SHADOW_WRAPPERS = {
    "core.alignment_constitution": "core.alignment.alignment_constitution",
    "core.auto_retrainer": "core.adaptation.auto_retrainer",
    "core.meta_cognition": "core.cognition.meta_cognition",
    "core.meta_controller": "core.cognition.meta_controller",
    "core.future_engine": "core.future.future_engine",
    "core.future_synthesis_engine": "core.future.future_synthesis_engine",
    "core.civilization_immune_system": "core.immune.civilization_immune_system",
    "core.self_modifier": "core.adaptation.self_modifier",
    "core.civilization_orchestrator": "core.orchestration.civilization_orchestrator",
}


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def classify(module: str) -> str:
    if module in SHADOW_WRAPPERS:
        return "shadow_wrapper"
    if module in PRODUCTION_MODULES:
        return "production"
    if module.startswith(PRODUCTION_PREFIXES):
        return "production"
    if module.startswith(RESEARCH_PREFIXES):
        return "research"
    return "support"


def iter_py_files() -> Iterable[Path]:
    ignored = {".venv", "__pycache__", ".git", "reports", "results", "logs", "data"}
    for path in ROOT.rglob("*.py"):
        if any(part in ignored for part in path.parts):
            continue
        yield path


def parse_imports(path: Path) -> Set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return set()

    imports: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def prefix_root(module: str) -> str:
    return module.split(".", 1)[0]


def build_graph() -> Tuple[Dict[str, Set[str]], Dict[str, str], Dict[str, Set[str]]]:
    modules: Dict[str, str] = {}
    graph: Dict[str, Set[str]] = defaultdict(set)
    reverse: Dict[str, Set[str]] = defaultdict(set)

    for path in iter_py_files():
        mod = module_name(path)
        modules[mod] = classify(mod)

    for path in iter_py_files():
        source = module_name(path)
        for imported in parse_imports(path):
            if imported in modules or any(imported == mod or imported.startswith(mod + ".") for mod in modules):
                graph[source].add(imported)
                reverse[imported].add(source)
            else:
                root = prefix_root(imported)
                if root in {"core", "learning", "meta", "scripts", "dashboard", "simulation", "execution", "infrastructure", "validation", "production", "research"}:
                    graph[source].add(imported)
    return graph, modules, reverse


def detect_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    index = 0
    stack: List[str] = []
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    on_stack: Set[str] = set()
    components: List[List[str]] = []

    def strongconnect(node: str):
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for successor in graph.get(node, set()):
            if successor not in indices:
                strongconnect(successor)
                lowlinks[node] = min(lowlinks[node], lowlinks[successor])
            elif successor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[successor])

        if lowlinks[node] == indices[node]:
            component = []
            while True:
                successor = stack.pop()
                on_stack.remove(successor)
                component.append(successor)
                if successor == node:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for node in graph:
        if node not in indices:
            strongconnect(node)
    return sorted(components, key=len, reverse=True)


def score_module(module: str, kind: str, graph: Dict[str, Set[str]], reverse: Dict[str, Set[str]], cycles: Sequence[Sequence[str]]) -> Dict[str, object]:
    outgoing = graph.get(module, set())
    incoming = reverse.get(module, set())
    external_research = sum(1 for dep in outgoing if any(dep.startswith(prefix) for prefix in RESEARCH_PREFIXES))
    external_production = sum(1 for dep in outgoing if any(dep.startswith(prefix) for prefix in PRODUCTION_PREFIXES))
    cycle_member = any(module in cycle for cycle in cycles)
    shadow = module in SHADOW_WRAPPERS

    risk = 0
    if kind == "production":
        risk += 10
    if kind == "research":
        risk += 55
    if kind == "shadow_wrapper":
        risk += 80
    if external_research > 0 and kind == "production":
        risk += min(30, external_research * 10)
    if cycle_member:
        risk += 25
    if len(outgoing) > 20:
        risk += 10
    if len(incoming) > 15:
        risk += 5
    if shadow:
        risk += 20

    risk = min(100, risk)
    readiness = max(0, 100 - risk)
    return {
        "module": module,
        "kind": kind,
        "outgoing": len(outgoing),
        "incoming": len(incoming),
        "research_edges": external_research,
        "production_edges": external_production,
        "cycle_member": cycle_member,
        "shadow_wrapper": shadow,
        "risk_score": risk,
        "production_readiness": readiness,
    }


def write_csv(path: Path, rows: Sequence[Dict[str, object]], fieldnames: Sequence[str]):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_graph_dot(path: Path, graph: Dict[str, Set[str]]):
    lines = ["digraph dependency_graph {"]
    for source, targets in sorted(graph.items()):
        for target in sorted(targets):
            lines.append(f'  "{source}" -> "{target}";')
    lines.append("}")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(outdir: Path = DEFAULT_OUTDIR):
    outdir.mkdir(parents=True, exist_ok=True)
    graph, modules, reverse = build_graph()
    cycles = detect_cycles(graph)

    rows = [score_module(module, kind, graph, reverse, cycles) for module, kind in sorted(modules.items())]
    rows = sorted(rows, key=lambda row: (int(row["risk_score"]), row["module"]), reverse=True)

    write_csv(
        outdir / "module_risk_score.csv",
        rows,
        ["module", "kind", "outgoing", "incoming", "research_edges", "production_edges", "cycle_member", "shadow_wrapper", "risk_score", "production_readiness"],
    )

    edge_rows = []
    for source, targets in sorted(graph.items()):
        for target in sorted(targets):
            edge_rows.append({"source": source, "target": target, "target_kind": classify(target) if target in modules else "external"})
    write_csv(outdir / "dependency_graph.csv", edge_rows, ["source", "target", "target_kind"])
    write_graph_dot(outdir / "dependency_graph.dot", graph)

    circular_rows = [{"cycle": " -> ".join(cycle)} for cycle in cycles]
    write_csv(outdir / "circular_dependencies.csv", circular_rows, ["cycle"]) if circular_rows else (outdir / "circular_dependencies.csv").write_text("cycle\n", encoding="utf-8")

    migration_plan = """# Migration Plan

1. Freeze production imports behind the new `production` boundary.
2. Quarantine research-only modules under the `research` boundary.
3. Remove or lazy-load production entrypoints that currently import research code.
4. Replace shadow wrappers with single-source modules or explicit facades.
5. Add dependency checks to CI for production modules.
"""
    (outdir / "migration_plan.md").write_text(migration_plan, encoding="utf-8")

    cleanup_roadmap = """# Cleanup Roadmap

1. Highest risk: main.py, core/system_orchestrator.py, simulation/live_simulation.py, core/auto_operator.py.
2. Next: shadow wrappers under core/*.py that re-export subpackage implementations.
3. Then: move experimental orchestration into research-only namespaces.
4. Finally: enforce import boundaries with a pre-commit or CI audit.
"""
    (outdir / "cleanup_roadmap.md").write_text(cleanup_roadmap, encoding="utf-8")

    readiness = [row for row in rows if row["kind"] == "production"]
    production_ready = [row for row in readiness if int(row["risk_score"]) <= 20]
    readiness_score = round(sum(int(row["production_readiness"]) for row in readiness) / max(len(readiness), 1), 2)

    evaluation = {
        "production_readiness_score": readiness_score,
        "production_modules_checked": len(readiness),
        "production_modules_ready": len(production_ready),
        "circular_dependencies": len(cycles),
        "shadow_wrappers": sum(1 for row in rows if row["shadow_wrapper"]),
        "risky_production_modules": [row["module"] for row in rows if row["kind"] == "production" and int(row["risk_score"]) > 20][:10],
    }
    (outdir / "production_readiness_evaluation.json").write_text(json.dumps(evaluation, indent=2, ensure_ascii=False), encoding="utf-8")

    evaluation_md = [
        "# Production Readiness Evaluation",
        "",
        f"- readiness score: {readiness_score}/100",
        f"- production modules checked: {len(readiness)}",
        f"- production modules ready: {len(production_ready)}",
        f"- circular dependencies: {len(cycles)}",
        f"- shadow wrappers: {evaluation['shadow_wrappers']}",
        f"- risky production modules: {', '.join(evaluation['risky_production_modules']) if evaluation['risky_production_modules'] else 'none'}",
        "",
        "## Interpretation",
        "",
        "The production path is partially isolated but still carries research leakage via top-level entrypoints and shadow wrappers.",
    ]
    (outdir / "production_readiness_evaluation.md").write_text("\n".join(evaluation_md), encoding="utf-8")

    print(f"Wrote architecture reports to {outdir}")


if __name__ == "__main__":
    main()
