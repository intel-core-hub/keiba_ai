# Pre-Contract Real Data Checklist

Created: 2026-06-18

Purpose: reduce paid JRA-VAN time by making the project ready before a contract
starts. This checklist does not approve production betting.

## Prepared Locally

- `approved_exports/` now exists as the local drop zone for real exports.
- Header templates are available under `approved_exports/templates/`.
- Root-level real export files are ignored by git.
- `scripts.check_approved_exports_ready` checks required files, columns, rows,
  and source labels before import.
- `pre_contract_sandbox/` now exists for non-evidence intake tests before a
  paid contract starts.
- `scripts.import_pre_contract_sandbox` imports sandbox CSVs only to
  non-canonical report paths and refuses canonical output roots.

## Files To Create After Contract

Place these files in `approved_exports/`:

- `schedule.csv`
- `odds.csv`
- `results.csv`

Use the templates:

- `approved_exports/templates/schedule.csv`
- `approved_exports/templates/odds.csv`
- `approved_exports/templates/results.csv`

Allowed `source` value for JV-Link:

```text
jvlink_export
```

## Pre-Import Check

Run this before touching `data/live_inputs`:

```powershell
python -m scripts.check_approved_exports_ready `
  --root approved_exports `
  --status reports/data_collection/approved_exports_pre_contract_status.json
```

Expected before contract:

```text
ready_for_import: false
reason: schedule.csv, odds.csv, and results.csv are not present yet
```

Expected after contract exports are placed:

```text
passed: true
ready_for_import: true
```

## Import Command After Files Are Ready

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

Then validate:

```powershell
python -m scripts.validate_live_inputs `
  --schedule data/live_inputs/today_races.json `
  --odds-dir data/live_inputs/odds `
  --min-races 12 `
  --min-horses-per-race 5 `
  --status reports/data_collection/live_input_validation_status_real.json
```

## Do Not Pay Yet If

- the importer tests are failing,
- the template check script is failing for reasons other than missing real files,
- `data/live_inputs` would need manual edits,
- the export source cannot be labeled `jvlink_export`, `approved_api`, or
  `manual_verified`,
- you expect the first three months to reliably recover the data fee.

## Optional Sandbox Test Before Contract

Use this only for parsing, timestamp, join, and safety checks. It is not Stage 4
evidence.

Use sandbox templates:

- `pre_contract_sandbox/templates/schedule.csv`
- `pre_contract_sandbox/templates/odds.csv`
- `pre_contract_sandbox/templates/results.csv`

Allowed sandbox source values:

```text
pre_contract_sandbox
manual_sample
public_sample
scrape_probe
```

Do not use approved source labels such as `jvlink_export` in the sandbox.

Run the built-in sample:

```powershell
python -m scripts.import_pre_contract_sandbox `
  --schedule-input pre_contract_sandbox/sample/schedule.csv `
  --odds-input pre_contract_sandbox/sample/odds.csv `
  --results-input pre_contract_sandbox/sample/results.csv `
  --output-root reports/data_collection/pre_contract_sandbox/live_inputs `
  --status reports/data_collection/pre_contract_sandbox_import_status.json `
  --clean `
  --min-races 1 `
  --min-horses-per-race 2
```

For your own small sample, place CSVs at:

- `pre_contract_sandbox/schedule.csv`
- `pre_contract_sandbox/odds.csv`
- `pre_contract_sandbox/results.csv`

Then run:

```powershell
python -m scripts.import_pre_contract_sandbox `
  --schedule-input pre_contract_sandbox/schedule.csv `
  --odds-input pre_contract_sandbox/odds.csv `
  --results-input pre_contract_sandbox/results.csv `
  --output-root reports/data_collection/pre_contract_sandbox/live_inputs `
  --status reports/data_collection/pre_contract_sandbox_import_status.json `
  --clean
```

The output report must say:

```text
evidence_eligible: false
```

## Contract-Day Goal

The first paid session should be used only for:

1. exporting real schedule, odds, and results,
2. placing them in `approved_exports/`,
3. running the pre-import check,
4. importing into `data/live_inputs`,
5. confirming the source is no longer `full_day_mock_fixture`.
