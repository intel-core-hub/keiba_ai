Governance checks
=================

This repository includes a set of lightweight governance tools and tests to enforce the
Adaptive Survival OS production rules. Files added:

- `docs/ADAPTIVE_SURVIVAL_OS.md` — constitutional text
- `scripts/runtime_import_scanner.py` — detects forbidden runtime imports
- `scripts/critical_path_linter.py` — detects forbidden critical-path constructs
- `scripts/duplicate_impl_detector.py` — detects duplicate top-level implementations
- `core/runtime_enforcement.py` — runtime guard helpers (imported opt-in)
- `tests/` — replay determinism and latency regression tests
- `.github/workflows/governance.yml` — CI workflow that runs checks and tests

Run locally:

```bash
python -m pip install -r requirements.txt
python scripts/runtime_import_scanner.py
python scripts/critical_path_linter.py
python scripts/duplicate_impl_detector.py
pytest -q
```

The latency test reads `.ci_latency.json` when present. CI will run all gates on push and PR.
