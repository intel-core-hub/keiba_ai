# Project Organization Audit - 2026-05-31

Purpose: separate production/runtime code, offline evidence tooling, canonical
artifacts, and generated workspace noise.

## Current Repository Shape

Top-level areas:

- `core/`: runtime and shared domain modules.
- `execution/`: operational loop entrypoints.
- `schemas/`: audit and decision event contracts.
- `scripts/`: offline analysis, evidence, release, and hygiene tools.
- `tests/`: regression and Stage 4 gate tests.
- `docs/`: human runbooks and project organization docs.
- `reports/stage4/`: Stage 4 evidence, blockers, daily status, and preflight
  records.
- `data/`: raw and processed historical datasets.
- `results/market_dependency/`: generated market independence evidence.
- `derived/`: report-only artifacts derived from canonical logs.
- `research/`, `learning/`, `simulation/`, `validation/`, `dashboard/`:
  offline, UI, or non-critical-path areas.

## Cleanup Applied

- Added `.gitignore` for local caches, virtual environments, repomix snapshots,
  downloaded CI artifacts, and ad-hoc load-test detail files.
- Added `docs/PROJECT_ORGANIZATION.md` as the project map and cleanup rulebook.
- Kept Stage 4 evidence artifacts visible and unignored.
- Removed local/generated files that are not required for project improvement or
  execution:
  - Python `__pycache__` directories outside `.venv`
  - `.pytest_cache`
  - repomix output snapshots
  - downloaded GitHub artifact directories
  - ad-hoc `reports/load_test_*` detail files

## What Remains Visible In Git Status

Meaningful untracked Stage 4 artifacts and new modules remain visible:

- `.ci_latency.json`
- `.github/workflows/stage4_release_gate.yml`
- `core/betting/risk_clamp.py`
- `derived/bets.csv`
- `docs/STAGE4_RELEASE_REHEARSAL_RUNBOOK.md`
- `logs/decisions.jsonl`
- `reports/stage4/`
- `results/market_dependency/`
- `schemas/audit_event.py`
- `schemas/decision_event.py`
- `scripts/stage4_*`
- `tests/test_stage4_readiness_gate.py`

This is intentional. These are not local noise; they are either implementation
or evidence that should be reviewed deliberately.

## Remaining Hygiene Debt

- 180 tracked `*.pyc` files were removed from the working tree and now appear
  as deletions. This should be kept as cleanup unless a reviewer explicitly
  wants compiled Python artifacts in git.
- Tracked repomix and downloaded artifact files were removed from the working
  tree and now appear as deletions. Future generated copies are ignored.
- Multiple deleted legacy modules remain in status. Do not restore or remove
  them casually; they appear to be part of the ongoing runtime-boundary cleanup.
- `reports/stage4/readiness_gate.json` still fails on:
  - `shadow_coverage`
  - `market_dependency`

## Verification

- `python -m pytest tests/test_stage4_readiness_gate.py tests/test_risk_clamp.py tests/test_latency_regression.py -q`
- Result: `41 passed`
- `python -m pytest tests/test_stage4_support_tools.py tests/test_stage4_readiness_gate.py tests/test_risk_clamp.py tests/test_latency_regression.py -q`
- Result: `46 passed`

## Code-Side Evidence Support Added

- `scripts/shadow_run_from_file.py`: appends strict shadow decisions from a
  real CSV/JSONL race input instead of synthetic races.
- `scripts/merge_market_snapshots.py`: merges real early/closing odds snapshot
  files into a historical dataset without copying existing odds columns.
- `scripts/stage4_survivability_report.py`: generates
  `reports/stage4/survivability_evaluation_v2.md` and `.json`.

## Recommended Next Cleanup Pass

1. Review whether tracked `*.pyc` files should be removed from git index.
2. Review whether tracked `repomix-output.xml` should remain versioned.
3. Commit Stage 4 evidence/tooling separately from unrelated refactors.
4. Keep `logs/decisions.jsonl` append-only and do not rewrite it for cleanup.
5. Do not delete `reports/stage4/*` unless replacing it with newer evidence and
   an audit note.

## Current Stage 4 Safety State

```text
Stage 4.2 Evidence-Blocked Candidate
Limited Production rehearsal: unavailable
Production Safe: unavailable
```

Passing evidence:

- replay mismatch = 0
- missing hash = 0
- snapshot-after-decision = 0
- RiskClamp bypass = 0
- stale-data bet = 0
- latency p999 passes
- timeout_rate = 0

Remaining blockers:

- 30 real calendar days shadow evidence is incomplete
- `early_odds_only` is unavailable
- `closing_odds` is unavailable
- operator preflight checks are not all true
