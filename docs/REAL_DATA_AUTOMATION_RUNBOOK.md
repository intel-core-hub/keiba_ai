# Real Data Automation Runbook

This runbook describes the offline evidence collection flow for Stage 4 real
data. It does not approve production betting. All commands below collect or
refresh evidence only.

## Purpose

The automation accumulates the real evidence needed for the remaining Stage 4
blockers:

- 30 calendar days of append-only shadow decisions in `logs/decisions.jsonl`
- real early and closing market snapshots
- race result / payout evidence
- feature snapshot and drift inputs

## Required Outputs

- `data/market_snapshots/early_odds.csv`
- `data/market_snapshots/closing_odds.csv`
- `data/results/race_results.csv`
- `data/feature_snapshots/YYYY-MM-DD/<race_id>.jsonl`
- `reports/data_collection/collection_status.json`
- `reports/data_collection/collection_errors.jsonl`
- `reports/data_collection/result_status.json`
- `reports/data_collection/result_errors.jsonl`
- `reports/drift/daily_feature_summary.csv`
- `reports/drift/daily_feature_psi.csv`
- `reports/drift/daily_prediction_summary.csv`
- `reports/data_collection/daily_update_status.json`

## Provider Boundary

The initial provider is `local_file`. It reads:

- `data/live_inputs/today_races.json`
- `data/live_inputs/odds/<race_id>.json`
- `data/live_inputs/results/<race_id>.json`

External scraping or API providers should be added behind the provider
interface in `core/data_sources/base.py`. Before adding a real provider,
confirm the source terms, robots policy, and contract/API permission. Do not
add prohibited access patterns.

`http` is now available as a generic provider for contract APIs or a local
mock server. It does not contain site-specific scraping logic. Configure it in
`config/real_data_provider.yaml`:

```yaml
provider: http
schedule_url: "http://localhost:8000/schedule"
odds_url_template: "http://localhost:8000/odds/{race_id}"
results_url_template: "http://localhost:8000/results/{race_id}"
timeout_seconds: 10
retry_limit: 2
retry_backoff_seconds: 0.25
user_agent: "keiba-ai-evidence-collector/0.1"
```

When pointing this provider at an external service, verify the terms of use,
robots policy, and explicit API or contract permission first. Use only
approved endpoints.

## Approved Data Import

Use `scripts.import_approved_real_data` to convert approved exports into the
`data/live_inputs` layout consumed by the gateway. Inputs can be `.csv`,
`.json`, or `.jsonl`.

Required input fields:

- Schedule: `race_id`, `race_start_at_utc`, optional `venue`, `race_number`, `source`
- Odds: `race_id`, `horse_id`, `odds`, `snapshot_at_utc`, optional `source`
- Results: `race_id`, `horse_id`, `finish_position`, `is_win`, `win_payout`, `result_time_utc`, optional `source`

Timestamps must be timezone-aware UTC ISO8601 strings such as
`2026-06-02T02:55:00+00:00`. The importer rejects missing `horse_id`, invalid
or non-positive odds, non-UTC timestamps, duplicate race/horse rows, and source
labels that are not one of `jvlink_export`, `approved_api`, or
`manual_verified`. Do not import `mock`, `copied`, `backdated`, `synthetic`, or
fixture-derived data as real evidence.

Example:

```powershell
python -m scripts.import_approved_real_data `
  --schedule-input approved_exports/schedule.csv `
  --odds-input approved_exports/odds.csv `
  --results-input approved_exports/results.csv `
  --output-root data/live_inputs `
  --source jvlink_export `
  --clean `
  --min-races 12 `
  --min-horses-per-race 5
```

For JV-Link exports, the dedicated wrapper fixes the source label to
`jvlink_export`:

```powershell
python -m scripts.import_jvlink_exports `
  --schedule-input approved_exports/schedule.csv `
  --odds-input approved_exports/odds.csv `
  --results-input approved_exports/results.csv `
  --output-root data/live_inputs `
  --clean `
  --min-races 12 `
  --min-horses-per-race 5
```

## Mock HTTP Provider Dry Run

Before connecting to any external service, run the built-in mock server and
confirm one full day of collection locally.

Start the mock provider on `localhost:8000`:

```powershell
python -m scripts.mock_real_data_provider_server `
  --data-root data/live_inputs/mock_server `
  --host 127.0.0.1 `
  --port 8000
```

This server exposes:

- `GET /schedule?target_date=YYYY-MM-DD`
- `GET /odds/{race_id}`
- `GET /results/{race_id}`

The default fixtures live under:

- `data/live_inputs/mock_server/today_races.json`
- `data/live_inputs/mock_server/odds/<race_id>.json`
- `data/live_inputs/mock_server/results/<race_id>.json`

Use this dry-run first so the `http` provider, collection scripts, and Stage 4
evidence path are verified before you attach a contract API or any approved
external provider.

## Local Real Data Gateway

After the mock dry-run, the next safe step is to run a local gateway that
serves approved inputs in the same HTTP schema. This keeps
`collect_market_snapshots`, `collect_race_results`, and
`daily_real_data_update` pointed at the generic `http` provider while the
upstream source can be swapped behind the gateway.

Start with the `local_file` backend:

```powershell
python -m scripts.real_data_gateway_server `
  --config config/real_data_gateway.yaml `
  --host 127.0.0.1 `
  --port 8000
```

`config/real_data_gateway.yaml`:

```yaml
backend: local_file
source_label: "local_gateway"
local_file:
  schedule_path: "data/live_inputs/today_races.json"
  odds_dir: "data/live_inputs/odds"
  results_dir: "data/live_inputs/results"
```

Point `config/real_data_provider.yaml` at this gateway:

```yaml
provider: http
schedule_url: "http://localhost:8000/schedule"
odds_url_template: "http://localhost:8000/odds/{race_id}"
results_url_template: "http://localhost:8000/results/{race_id}"
timeout_seconds: 10
retry_limit: 2
retry_backoff_seconds: 0.25
user_agent: "keiba-ai-evidence-collector/0.1"
```

The gateway currently implements `local_file` only. `contract_api` /
`approved_api` are intentionally reserved for explicit approved adapters and
fail closed until such an adapter is implemented. Do not add unauthorized
scraping to the gateway. For external data, confirm terms of use, robots
policy, and explicit API or contract permission before enabling the adapter.

## Market Snapshot Collection

Run this every 5 minutes during racing hours:

```powershell
python -m scripts.collect_market_snapshots `
  --provider local_file `
  --schedule data/live_inputs/today_races.json `
  --odds-dir data/live_inputs/odds `
  --early-minutes-before 30 `
  --closing-minutes-before 5 `
  --window-minutes 3 `
  --early-output data/market_snapshots/early_odds.csv `
  --closing-output data/market_snapshots/closing_odds.csv `
  --status reports/data_collection/collection_status.json `
  --errors reports/data_collection/collection_errors.jsonl
```

The script writes only races inside the configured early or closing window. It
deduplicates by `race_id` and `horse_id` within each output file. Invalid odds,
missing horse IDs, missing snapshot times, and provider errors are written to
`reports/data_collection/collection_errors.jsonl`.

To collect from a contract API or local mock HTTP service instead:

```powershell
python -m scripts.collect_market_snapshots `
  --provider http `
  --provider-config config/real_data_provider.yaml `
  --early-minutes-before 30 `
  --closing-minutes-before 5 `
  --window-minutes 3 `
  --early-output data/market_snapshots/early_odds.csv `
  --closing-output data/market_snapshots/closing_odds.csv `
  --status reports/data_collection/collection_status.json `
  --errors reports/data_collection/collection_errors.jsonl
```

## Race Result Collection

Run this after races have results:

```powershell
python -m scripts.collect_race_results `
  --provider local_file `
  --schedule data/live_inputs/today_races.json `
  --results-dir data/live_inputs/results `
  --output data/results/race_results.csv `
  --status reports/data_collection/result_status.json `
  --errors reports/data_collection/result_errors.jsonl
```

The script deduplicates by `race_id` and `horse_id`. Negative payouts and
provider errors are written to `reports/data_collection/result_errors.jsonl`.

HTTP provider example:

```powershell
python -m scripts.collect_race_results `
  --provider http `
  --provider-config config/real_data_provider.yaml `
  --output data/results/race_results.csv `
  --status reports/data_collection/result_status.json `
  --errors reports/data_collection/result_errors.jsonl
```

## Nightly Update

Run this after the day is complete:

```powershell
python -m scripts.daily_real_data_update `
  --provider local_file `
  --schedule data/live_inputs/today_races.json `
  --odds-dir data/live_inputs/odds `
  --results-dir data/live_inputs/results `
  --baseline data/processed/historical_dataset.csv
```

The wrapper runs:

1. `collect_market_snapshots`
2. `collect_race_results`
3. `daily_drift_report`
4. `derive_bets_csv_from_decisions`
5. `stage4_current_update`

`stage4_current_update` keeps the existing Stage 4 policy: if
`early_odds.csv` and `closing_odds.csv` are not both available, the market
dependency blocker remains explicit. The wrapper never fabricates missing
evidence.

HTTP provider example:

```powershell
python -m scripts.daily_real_data_update `
  --provider http `
  --provider-config config/real_data_provider.yaml `
  --baseline data/processed/historical_dataset.csv
```

## Drift Report

Validate that the approved live inputs cover the intended day before building
feature snapshots. For a normal full-day run, set `--min-races` to the expected
number of races and `--min-horses-per-race` to the smallest valid field size
for the day.

```powershell
python -m scripts.validate_live_inputs `
  --schedule data/live_inputs/today_races.json `
  --odds-dir data/live_inputs/odds `
  --min-races 12 `
  --min-horses-per-race 5 `
  --status reports/data_collection/live_input_validation.json
```

Then build current feature snapshots from approved live inputs before running
the drift report. This step reads every `data/live_inputs/odds/<race_id>.json`
file, ranks horses by odds, and writes one pre-race feature snapshot per horse.
It does not use results or payouts.

```powershell
python -m scripts.build_live_feature_snapshots `
  --schedule data/live_inputs/today_races.json `
  --odds-dir data/live_inputs/odds `
  --output-root data/feature_snapshots `
  --snapshot-time-utc 2026-06-02T02:55:00+00:00 `
  --feature-version live_market_v1 `
  --validate-min-races 12 `
  --validate-min-horses-per-race 5
```

For a meaningful PSI verdict, use a full approved racing day rather than a
single race or a two-horse fixture. Very small current samples can legitimately
produce `severe` even when the pipeline is working.

To refresh drift only:

```powershell
python -m scripts.daily_drift_report `
  --baseline data/processed/historical_dataset.csv `
  --feature-snapshots data/feature_snapshots `
  --decision-log logs/decisions.jsonl `
  --results data/results/race_results.csv `
  --outdir reports/drift `
  --top-features odds_value,favorite_rank,distance,market_support,track_affinity
```

PSI status values:

- `< 0.10`: `stable`
- `< 0.20`: `watch`
- `< 0.30`: `warning`
- `>= 0.30`: `severe`

Missing baseline or current data is reported as `insufficient_data`, not as a
pass.

## Failure Checks

When a collection step fails, check:

- `reports/data_collection/collection_errors.jsonl`
- `reports/data_collection/result_errors.jsonl`
- `reports/data_collection/daily_update_status.json`
- `reports/drift/daily_drift_status.json`
- `reports/stage4/readiness_gate.json`

Provider errors should remain visible as `provider_error`, `missing`, `stale`,
or `insufficient_data` style statuses. Do not hide them by creating placeholder
success rows.

## Never Do

- Do not backdate timestamps.
- Do not copy `odds` into `early_odds`.
- Do not copy `odds_value` into `closing_odds`.
- Do not set manual preflight values to true without evidence.
- Do not use synthetic fixtures to satisfy Stage 4 blockers.
- Do not edit `derived/bets.csv` by hand.
- Do not recreate `logs/decisions.jsonl` during the 30-day shadow run.

`logs/decisions.jsonl` remains the canonical append-only evidence log.
`derived/bets.csv` is report-only and must be regenerated from the canonical
JSONL.
