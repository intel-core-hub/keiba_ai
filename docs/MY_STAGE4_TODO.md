# Current Stage 4 TODO

Updated: 2026-06-18

## Today Status

- Revised plan is now active: `docs/STAGE4_RECOVERY_PLAN_2026-06-18.md`.
- Checked for approved real exports under `approved_exports/`; the directory is missing.
- Current `data/live_inputs` source is still `full_day_mock_fixture`; it is plumbing evidence only, not production evidence.
- Because approved real exports are unavailable, no import was run today.
- No mock dry-run was run as Stage 4 progress today.
- No canonical `data/market_snapshots` or `data/results` files were overwritten today.
- Blocked status was recorded in `reports/data_collection/real_data_blocked_status_20260618.json`.
- Pre-contract real-data intake prep was completed:
  - `approved_exports/` drop zone was created.
  - CSV header templates were added under `approved_exports/templates/`.
  - `scripts.check_approved_exports_ready` was added for pre-import checks.
  - `reports/data_collection/approved_exports_pre_contract_status.json` confirms real exports are still missing.
- Pre-contract sandbox testing was added:
  - `pre_contract_sandbox/` was created for non-evidence samples.
  - `scripts.import_pre_contract_sandbox` was added.
  - The sandbox importer refuses canonical output roots such as `data/live_inputs`.
  - Built-in sandbox sample import passed and wrote only under `reports/data_collection/pre_contract_sandbox/`.
  - `reports/data_collection/pre_contract_sandbox_import_status.json` records `evidence_eligible: false`.
- Public low-volume sandbox race samples were expanded:
  - Races: 2025-06-01 Tokyo 9R, 10R, 11R, 12R.
  - Files: `pre_contract_sandbox/schedule.csv`, `pre_contract_sandbox/odds.csv`, `pre_contract_sandbox/results.csv`.
  - Rows: 4 schedule rows, 70 odds rows, 70 result rows.
  - Source label: `scrape_probe`.
  - Import and validation passed, still with `evidence_eligible: false`.
- Multi-race sandbox Shadow run was executed outside canonical evidence:
  - Shadow input: `reports/data_collection/pre_contract_sandbox/shadow_input.csv`.
  - Sandbox decision log: `reports/data_collection/pre_contract_sandbox/multi_race_decisions_20260618_01.jsonl`.
  - Sandbox bets report: `reports/data_collection/pre_contract_sandbox/multi_race_bets_20260618_01.csv`.
  - 6 shadow candidates were generated and settled across 3 races.
  - All 6 were rejected by shadow execution (`api_status=shadow`), so no live bet was sent.
  - Paper result: stake 600, profit -950, hits 0, ROI -158.33%.
  - Candidate tendency: 5 / 6 candidates were `DEEP_LONGSHOT`, and 3 / 6 were favorite rank 9 or worse.
  - Canonical `logs/decisions.jsonl` and `derived/bets.csv` were not touched.
- Pre-contract sandbox evaluation was recorded:
  - JSON: `reports/data_collection/pre_contract_sandbox_eval_status.json`.
  - Markdown: `reports/data_collection/pre_contract_sandbox_eval.md`.
  - Main finding: before paying for approved data, the current candidate selection should be treated as too longshot-heavy until larger sandbox or approved Shadow evidence says otherwise.
- Conservative filter analysis was added:
  - Script: `scripts/analyze_pre_contract_filters.py`.
  - JSON: `reports/data_collection/pre_contract_sandbox_filter_analysis_status.json`.
  - Markdown: `reports/data_collection/pre_contract_sandbox_filter_analysis.md`.
  - In this small sandbox set, excluding `DEEP_LONGSHOT` reduced paper profit from `-950` to `-100`, but also reduced candidates from 6 to 1.
- Stage 4 release gate is still blocked by evidence requirements.
- `logs/decisions.jsonl` exists and must remain the canonical append-only evidence log.

## P0 Blockers

- `shadow_coverage.calendar_days < 30`
  - Current detail from readiness output: 2 / 30 calendar days.
- Market dependency blocker:
  - `DEEP_LONGSHOT` odds bucket is missing.
  - `market_dependency_report --strict` is still blocked by available evidence.

## Cleared And Still Passing

- Critical path coverage:
  - Branch coverage is 84.0596%, above the 80% gate.
  - `scripts/bet_type_metrics_report.py` is present in critical coverage evidence.
  - `missing_critical_files` is empty.
- Metric gate:
  - `metric_gate.passed` is true.

## Evidence Files Confirmed

- `reports/stage4/readiness_gate.json`
- `reports/stage4/critical_path_coverage.json`
- `reports/stage4/evidence_summary.json`
- `reports/stage4/current_update_summary.json`
- `reports/stage4/evidence_blockers.md`
- `reports/stage4/survivability_evaluation_v2.json`
- `reports/stage4/preflight_status.json`
- `reports/stage4/degradation_mode_report.json`
- `reports/data_collection/live_input_validation_status.json`
- `reports/data_collection/live_input_validation_status_20260606.json`
- `reports/data_collection/live_input_validation_status_20260607.json`
- `reports/data_collection/live_input_validation_status_20260608.json`
- `reports/data_collection/live_input_validation_status_20260609.json`
- `reports/data_collection/live_input_validation_status_20260612.json`
- `reports/data_collection/live_input_validation_status_20260614.json`
- `reports/data_collection/live_input_validation_status_20260616.json`
- `reports/data_collection/live_input_validation_status_20260617.json`
- `reports/data_collection/approved_exports_pre_contract_status.json`
- `reports/data_collection/pre_contract_sandbox_import_status.json`
- `reports/data_collection/pre_contract_sandbox_validation_status.json`
- `reports/data_collection/pre_contract_sandbox_shadow_input_status.json`
- `reports/data_collection/pre_contract_sandbox_shadow_run_status.json`
- `reports/data_collection/pre_contract_sandbox_eval_status.json`
- `reports/data_collection/pre_contract_sandbox_eval.md`
- `reports/data_collection/pre_contract_sandbox_filter_analysis_status.json`
- `reports/data_collection/pre_contract_sandbox_filter_analysis.md`
- `data/market_snapshots/early_odds.csv`
- `data/market_snapshots/closing_odds.csv`
- `data/results/race_results.csv`

## Latest Dry-Run Files Confirmed

These files validate the local-file collection route only. Do not use them as Stage 4 production evidence.

- `reports/data_collection/mock_dry_run_20260617/early_odds.csv`: 8 rows
- `reports/data_collection/mock_dry_run_20260617/closing_window_closing_odds.csv`: 8 rows
- `reports/data_collection/mock_dry_run_20260617/race_results.csv`: 96 rows

## Current Counts

- `logs/decisions.jsonl`: 342 lines
- `derived/bets.csv`: 123 rows
- `data/market_snapshots/early_odds.csv`: 2 rows
- `data/market_snapshots/closing_odds.csv`: 2 rows
- `data/results/race_results.csv`: 2 rows
- Live input validation: 12 races / 96 horses
- Pre-contract sandbox input: 4 races / 70 horses
- Pre-contract multi-race sandbox Shadow: 6 candidates / 0 hits / -950 paper profit
- Conservative filter check: excluding `DEEP_LONGSHOT` leaves 1 candidate / -100 paper profit

## Rule

- No production betting.
- Keep `SHADOW_MODE=1` and `SAFE_MODE=1`.
- Do not delete, recreate, or rewrite `logs/decisions.jsonl`.
- Do not manually edit `derived/bets.csv`.
- Do not treat synthetic fixtures as production evidence.
- Do not copy `odds` into `early_odds`.
- Do not copy `odds_value` into `closing_odds`.
- Do not set preflight checks to true without evidence.

## Next Actions

- Prepare approved real exports under `approved_exports/`:
  - `schedule.csv`
  - `odds.csv`
  - `results.csv`
- Use an allowed source label:
  - `jvlink_export`
  - `approved_api`
  - `manual_verified`
- Run `python -m scripts.check_approved_exports_ready --root approved_exports --status reports/data_collection/approved_exports_pre_contract_status.json` before import.
- Use `pre_contract_sandbox/` only for parser/join/safety tests and early loss-risk checks. Do not treat its output as Stage 4 evidence.
- Before spending on approved data, either add more sandbox races or add a conservative candidate filter experiment for `DEEP_LONGSHOT` / favorite-rank-9-plus selections.
- Replace `full_day_mock_fixture` inputs with approved real exports before writing to canonical `data/market_snapshots` and `data/results`.
- After approved import, append real Shadow evidence until 30 calendar days are reached.
- Expand real market snapshots so `race_id,horse_id` joins produce matched rows.
- Add real `DEEP_LONGSHOT` coverage or document why the approved real data cannot yet satisfy it.
