# Cleanup Roadmap

1. Highest risk: main.py, core/system_orchestrator.py, simulation/live_simulation.py, core/auto_operator.py.
2. Next: shadow wrappers under core/*.py that re-export subpackage implementations.
3. Then: move experimental orchestration into research-only namespaces.
4. Finally: enforce import boundaries with a pre-commit or CI audit.
