# Stage 4 Recovery Plan

Created: 2026-06-18  
Supersedes: `docs/STAGE4_EXECUTION_PLAN_2026-06-04.docx` as the active execution plan  
Status: revised plan after discovering daily mock dry-runs do not advance Stage 4 evidence gates

## Executive Summary

The previous daily loop proved that the collection plumbing still works, but it did not move the Stage 4 release gate. The reason is simple: the daily outputs under `reports/data_collection/mock_dry_run_YYYYMMDD/` are mock dry-runs and are not counted by `scripts.stage4_readiness_gate`.

This revised plan changes the objective from "run the daily checklist" to "move the gate metrics that are actually blocking release."

The active blockers are:

- `shadow_coverage.calendar_days < 30`
- `market_dependency.DEEP_LONGSHOT bucket missing`

The cleared items that should be preserved are:

- Critical path coverage is passing at `84.0596%`, above the 80% gate.
- `scripts/bet_type_metrics_report.py` is present in critical coverage evidence.
- Metric gate is passing.
- Replay, event chain, latency, governance lint, and shadow safety are currently passing.

## Current Baseline

As of the latest readiness output:

- Stage verdict: `EVIDENCE_BLOCKED`
- Shadow evidence: `2 / 30` calendar days
- Shadow evidence source: `logs/decisions.jsonl`
- Market blocker: missing `DEEP_LONGSHOT` odds bucket
- Current `data/live_inputs` source: `full_day_mock_fixture`
- Current canonical market snapshot rows:
  - `data/market_snapshots/early_odds.csv`: 2 rows
  - `data/market_snapshots/closing_odds.csv`: 2 rows
  - `data/results/race_results.csv`: 2 rows
- Current decision log:
  - `logs/decisions.jsonl`: 342 lines
- Current derived report:
  - `derived/bets.csv`: 123 rows

Important diagnosis:

- `shadow_coverage` is calculated from event timestamps in `logs/decisions.jsonl`.
- The daily mock dry-run directories are not read by the readiness gate.
- Repeating mock dry-runs will keep producing the same gate result.

## Recovery Objective

Bring Stage 4 from `EVIDENCE_BLOCKED` to a release-candidate state by producing real, append-only evidence that satisfies the actual readiness checks.

The plan is successful only when:

- `shadow_coverage.calendar_days >= 30`
- `market_dependency.passed == true`
- `critical_path_coverage.passed == true`
- `metric_gate.passed == true`
- `evidence_gate.passed == true`
- `stage4_verdict` is no longer `EVIDENCE_BLOCKED`

## Evidence Policy

The following rules are mandatory:

- No production betting.
- Keep `SHADOW_MODE=1` and `SAFE_MODE=1`.
- Do not delete, recreate, or rewrite `logs/decisions.jsonl`.
- Do not manually edit `derived/bets.csv`.
- Do not treat synthetic fixtures as production evidence.
- Do not backdate events to satisfy the 30-day gate.
- Do not copy `odds` into `early_odds`.
- Do not copy `odds_value` into `closing_odds`.
- Do not set preflight checks to true without evidence.

Allowed real-data source labels are:

- `jvlink_export`
- `approved_api`
- `manual_verified`

Rejected source labels include:

- `mock`
- `synthetic`
- `fixture`
- `copied`
- `backdated`

## Workstream A: Stop The Ineffective Daily Loop

Goal: prevent more days from being spent on mock-only activity that does not move the gate.

### A1. New Daily Rule

Before running any daily evidence task, check the source in `data/live_inputs/today_races.json`.

If the source is still `full_day_mock_fixture`:

- Do not run the full daily mock dry-run as the main task.
- Do not update canonical market snapshot files.
- Report the day as blocked on real input.
- Spend the task window on real-data import or Shadow evidence setup instead.

Mock dry-runs are still allowed only when:

- a collection script changed,
- a provider integration changed,
- a schema validation rule changed,
- or a one-time smoke test is needed.

### A2. Daily Success Metric

A daily task counts as progress only if at least one of these changes:

- `shadow_coverage.calendar_days` increases.
- `data/live_inputs` changes from `full_day_mock_fixture` to an approved source.
- real early/closing market snapshots are imported or merged.
- `market_dependency` no longer reports missing `DEEP_LONGSHOT`.
- a blocking readiness reason disappears.

## Workstream B: Approved Real Data Intake

Goal: replace `full_day_mock_fixture` with approved real input files.

### B1. Required Inputs

Prepare approved exports with these fields.

Schedule:

- `race_id`
- `race_start_at_utc`
- optional `venue`
- optional `race_number`
- optional `source`

Odds:

- `race_id`
- `horse_id`
- `odds`
- `snapshot_at_utc`
- optional `source`

Results:

- `race_id`
- `horse_id`
- `finish_position`
- `is_win`
- `win_payout`
- `result_time_utc`
- optional `source`

All timestamps must be timezone-aware UTC ISO8601 strings, for example:

```text
2026-06-18T02:55:00+00:00
```

### B2. Import Command

Use one of these commands.

For generic approved data:

```powershell
python -m scripts.import_approved_real_data `
  --schedule-input approved_exports/schedule.csv `
  --odds-input approved_exports/odds.csv `
  --results-input approved_exports/results.csv `
  --output-root data/live_inputs `
  --source manual_verified `
  --clean `
  --min-races 12 `
  --min-horses-per-race 5 `
  --status reports/data_collection/import_approved_real_data_status.json
```

For JV-Link exports:

```powershell
python -m scripts.import_jvlink_exports `
  --schedule-input approved_exports/schedule.csv `
  --odds-input approved_exports/odds.csv `
  --results-input approved_exports/results.csv `
  --output-root data/live_inputs `
  --clean `
  --min-races 12 `
  --min-horses-per-race 5 `
  --status reports/data_collection/import_jvlink_exports_status.json
```

### B3. Validation Command

After import:

```powershell
python -m scripts.validate_live_inputs `
  --schedule data/live_inputs/today_races.json `
  --odds-dir data/live_inputs/odds `
  --status reports/data_collection/live_input_validation_status_real.json
```

### B4. Acceptance Criteria

This workstream is complete when:

- `data/live_inputs/today_races.json` no longer says `full_day_mock_fixture`.
- the source is one of `jvlink_export`, `approved_api`, or `manual_verified`.
- validation passes.
- the imported races and horses are plausible for a real racing day.

## Workstream C: Shadow Evidence Accumulation

Goal: increase `shadow_coverage.calendar_days` from `2 / 30` to `30 / 30`.

### C1. Source Of Truth

The readiness gate reads Shadow coverage from:

```text
logs/decisions.jsonl
```

It counts unique calendar dates from event timestamps such as:

- `occurred_at_utc`
- `timestamp`
- `decision_time_utc`

Daily dry-run reports do not count.

### C2. Shadow Append Options

For real race/market input files:

```powershell
python -m scripts.shadow_run_from_file `
  --input path/to/approved_shadow_input.csv `
  --decision-log logs/decisions.jsonl `
  --csv-report reports/stage4/shadow_run_YYYYMMDD.csv `
  --settle
```

For just-in-time race checks:

```powershell
python -m scripts.stage4_jit_shadow_runner `
  --races-file path/to/approved_races.json `
  --minutes-before 10 `
  --output-dir reports/stage4/jit_shadow `
  --decision-log logs/decisions.jsonl `
  --csv-report reports/stage4/jit_shadow_YYYYMMDD.csv `
  --replay-report reports/stage4/replay_report.json `
  --summary reports/stage4/jit_shadow_summary_YYYYMMDD.json
```

### C3. Daily Shadow Evidence Checklist

Each valid Shadow evidence day must produce:

- new append-only events in `logs/decisions.jsonl`
- event timestamps for the current UTC calendar day
- no accepted real bets
- no non-shadow submissions
- replay mismatch count remains 0
- readiness output shows the same or higher `shadow_coverage.calendar_days`

### C4. Schedule

If the existing two days remain valid, the remaining requirement is 28 additional unique calendar days.

If the old two days are rejected or quarantined later, restart the count from 0 and collect 30 new days.

No backfill is allowed.

## Workstream D: Real Market Snapshot Evidence

Goal: clear `market_dependency.DEEP_LONGSHOT bucket missing`.

### D1. Required Snapshot Files

Real early snapshot file:

- `race_id`
- `horse_id` or `selection_id`
- `snapshot_time`
- odds column, such as `early_odds`, `odds_t60`, or `opening_odds`

Real closing snapshot file:

- `race_id`
- `horse_id` or `selection_id`
- `snapshot_time`
- odds column, such as `closing_odds`, `final_odds`, or `market_odds`

### D2. Merge Command

```powershell
python -m scripts.merge_market_snapshots `
  --base data/processed/historical_dataset.csv `
  --output data/processed/historical_dataset_with_market_snapshots.csv `
  --join-keys race_id,horse_id `
  --early-snapshot path/to/real_early_snapshot.csv `
  --closing-snapshot path/to/real_closing_snapshot.csv
```

### D3. Market Dependency Command

```powershell
python -m scripts.market_dependency_report `
  --input data/processed/historical_dataset_with_market_snapshots.csv `
  --outdir results/market_dependency `
  --strict
```

### D4. Acceptance Criteria

This workstream is complete when:

- `early_odds_only` is available.
- `closing_odds` is available.
- `FAVORITE_HEAVY`, `LONGSHOT`, and `DEEP_LONGSHOT` all have evidence rows.
- `reports/stage4/readiness_gate.json` no longer fails on `market_dependency`.

## Workstream E: Gate Hygiene And Reporting

Goal: keep already-cleared gates from regressing.

### E1. Critical Path Coverage

Run after code changes, not as fake daily progress:

```powershell
python -m pytest -q `
  --cov=core `
  --cov=scripts.stage4_readiness_gate `
  --cov=scripts.bet_type_metrics_report `
  --cov-branch `
  --cov-report=json:reports/stage4/critical_path_coverage.json `
  tests/test_replay_determinism.py `
  tests/test_replay_engine_coverage.py `
  tests/test_risk_clamp.py `
  tests/test_bet_executor_ev.py `
  tests/test_critical_path_coverage_gate.py `
  tests/test_latency_regression.py `
  tests/test_stage4_readiness_gate.py `
  tests/test_bet_types.py `
  tests/test_bet_type_metrics_report.py
```

Acceptance:

- test command passes
- readiness critical path coverage remains above 80%
- `missing_critical_files` remains empty

### E2. Readiness Gate

Run after evidence changes:

```powershell
python -m scripts.stage4_readiness_gate `
  --decision-log logs/decisions.jsonl `
  --latency .ci_latency.json `
  --market-outdir results/market_dependency `
  --derived-bets derived/bets.csv `
  --coverage-json reports/stage4/critical_path_coverage.json `
  --replay-report reports/stage4/replay_report.json `
  --require-replay-report `
  --output reports/stage4/readiness_gate.json
```

Acceptance:

- blocking reasons decrease over time
- no new metric failures appear
- no production safety failures appear

## Revised 30-Day Calendar

This plan starts from the first day approved real evidence is available. Calendar dates should not be counted from mock dry-runs.

### Day 0: Recovery Setup

- Stop treating mock dry-run as progress.
- Identify the approved real data source.
- Create or obtain exports for schedule, odds, and results.
- Confirm source label is allowed.
- Confirm no production betting.

### Days 1-3: Real Data Import And First Shadow Append

- Import approved real data into `data/live_inputs`.
- Validate imported live inputs.
- Run one real Shadow append into `logs/decisions.jsonl`.
- Run readiness gate.
- Confirm `shadow_coverage.calendar_days` increases.

### Days 4-10: Market Snapshot Repair

- Collect real early snapshots.
- Collect real closing snapshots.
- Merge snapshots into processed historical dataset.
- Regenerate market dependency report.
- Specifically verify `DEEP_LONGSHOT`.

### Days 11-30: Evidence Accumulation

- Append one valid Shadow evidence day per calendar day.
- Run readiness gate after each append.
- Track `shadow_coverage.calendar_days`.
- Keep metric gate passing.
- Do not run mock-only days as progress.

### Final Gate Day

Run the full gate bundle:

- critical path coverage
- readiness gate
- evidence bundle
- survivability report
- blocker report
- rubric report

Release candidate is allowed only if:

- `stage4_verdict` is no longer evidence-blocked
- non-shadow blockers are empty
- production safety checks remain true

## Daily Progress Template

Use this template in `docs/MY_STAGE4_TODO.md` or daily status reports:

```markdown
Date:

Input source:
Approved source? yes/no

Shadow calendar days before:
Shadow calendar days after:
Decision log appended? yes/no

Market dependency before:
Market dependency after:
DEEP_LONGSHOT present? yes/no

Readiness blockers before:
Readiness blockers after:

Canonical files changed:
Safety notes:
Next blocker:
```

## Stop Conditions

Stop and report instead of continuing if:

- input source is still `full_day_mock_fixture`
- approved exports are missing
- importer rejects timestamps or duplicate rows
- `logs/decisions.jsonl` would need manual editing
- Shadow run would submit real bets
- early or closing odds would require copied/synthetic columns
- readiness gate shows a new safety failure

## Immediate Next Task

The next task should not be another mock dry-run.

The next task should be:

1. locate or create approved real export files under an `approved_exports/` directory,
2. run `scripts.import_approved_real_data` or `scripts.import_jvlink_exports`,
3. validate that `data/live_inputs` no longer uses `full_day_mock_fixture`,
4. append the first real Shadow evidence day to `logs/decisions.jsonl`,
5. confirm `shadow_coverage.calendar_days` increases from 2.

If approved real exports are not available, the correct daily status is:

```text
Blocked: no approved real exports available. Mock dry-run does not advance Stage 4.
```
