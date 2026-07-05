# Project Organization

This project is currently organized around one production-safety principle:
runtime code, offline research, and evidence artifacts must stay visibly
separate.

## Runtime Allowed

These modules are the production/shadow execution core. Keep this path small,
deterministic, and free of research/dashboard imports.

- `core/betting/decision_engine.py`
- `core/betting/bet_types.py`
- `core/betting/risk_clamp.py`
- `core/survival/degradation_mode.py`
- `core/execution/bet_executor.py`
- `core/low_latency_execution.py`
- `core/circuit_breaker.py`
- `core/prediction/edge_calculator.py`
- `schemas/decision_event.py`
- `schemas/audit_event.py`

Runtime must fail closed on stale data, missing hashes, RiskClamp failure,
session/API errors, and audit-chain failures.

## Release Gate Only

These scripts decide release/rehearsal readiness or assemble release evidence.
They must not be imported into the race-close critical path.

- `scripts/stage4_readiness_gate.py`
- `scripts/stage4_evidence_bundle.py`
- `scripts/stage4_rehearsal_evidence.py`
- `scripts/stage4_current_update.py`
- `scripts/latency_regression_guard.py`
- `scripts/degradation_mode_report.py`

## Evidence Generation Only

These tools create reports or derived artifacts from canonical evidence. They
are useful for operators and audit review, but they are not runtime inputs.

- `scripts/derive_bets_csv_from_decisions.py`
- `scripts/market_dependency_report.py`
- `scripts/merge_market_snapshots.py`
- `scripts/shadow_run_from_file.py`
- `scripts/stage4_survivability_report.py`
- `scripts/stage4_evidence_blockers_report.py`

## Offline Research Only

These areas may be used for experimentation, analysis, and validation outside
the execution path.

- `research/`
- `learning/`
- `tools/`
- `core/adaptation/`

## Dashboard / Read-Only Only

Dashboard code can read evidence and status artifacts. It must not create bets,
alter canonical evidence, or participate in race-close decisions.

- `dashboard/`

## Forbidden In Runtime

The following must remain outside the runtime critical path.

- `scripts/stage4_readiness_gate.py`
- `scripts/stage4_evidence_bundle.py`
- `scripts/stage4_survivability_report.py`
- `scripts/merge_market_snapshots.py`
- `scripts/shadow_run_from_file.py`
- `scripts/market_dependency_report.py`
- `research/`
- `learning/`
- `dashboard/`
- `tools/`
- `core/adaptation/`

## Runtime Boundary Guards

These scripts are allowed to inspect the runtime boundary from CI/release jobs,
but they are not runtime dependencies.

- `scripts/runtime_import_scanner.py`
- `scripts/critical_path_linter.py`

## Canonical Evidence

These artifacts are meaningful audit evidence and should not be casually
deleted or regenerated without recording why.

- `logs/decisions.jsonl`: canonical append-only shadow decision/event log.
- `reports/stage4/replay_report.json`: replay cleanliness evidence.
- `reports/stage4/readiness_gate.json`: current Stage 4 gate result.
- `reports/stage4/*`: Stage 4 runbooks, blockers, daily status, and preflight
  evidence.
- `.ci_latency.json`: current CI latency gate payload.
- `results/market_dependency/*`: current market independence evidence.
- `derived/bets.csv`: report artifact regenerated from `logs/decisions.jsonl`;
  never authoritative.

## Generated Or Local-Only Files

These are workspace noise or reproducible generated files. They should stay out
of git unless a reviewer explicitly needs a specific artifact.

- `__pycache__/`, `*.pyc`, `.pytest_cache/`
- `.venv/`
- `repomix-output*.xml`
- `gh_artifacts*/`
- `reports/load_test_*.csv`
- `reports/load_test_*.json`
- `reports/load_test_*.png`

## Current Stage 4 Position

Current classification remains:

```text
Stage 4.2 Evidence-Blocked Candidate
Limited Production rehearsal: unavailable
Production Safe: unavailable
```

Known hard blockers:

- `shadow_coverage.calendar_days < 30`
- `early_odds_only` unavailable
- `closing_odds` unavailable

Operator preflight drill evidence is complete in the current Stage 4 artifact
set; it is no longer a remaining blocker unless future evidence regeneration
changes `reports/stage4/preflight_status.json` or the drill evidence files.

Code-side support now exists for the remaining evidence work:

- Use `scripts/shadow_run_from_file.py` to append strict shadow decisions from
  a real race/market input file without synthetic race generation.
- Use `scripts/merge_market_snapshots.py` to merge real early/closing odds
  snapshot files into a processed historical dataset.
- Use `scripts/stage4_survivability_report.py` to emit the v2.0 markdown and
  JSON evaluation from current Stage 4 artifacts.
- Use `scripts/stage4_current_update.py` after real daily shadow append or real
  market snapshot ingestion to refresh the current evidence bundle without
  fabricating blocked evidence.

Do not satisfy these blockers with synthetic fixtures, backdated timestamps,
copied odds columns, or manual true values.

## Cleanup Rule

Before deleting or moving anything, classify it as one of:

1. runtime critical path
2. offline/evidence tooling
3. canonical evidence
4. generated/local-only noise
5. archived research

Only category 4 is safe to remove automatically. Categories 1-3 require tests or
audit review. Category 5 can be moved only when imports prove it is not in the
runtime path.
