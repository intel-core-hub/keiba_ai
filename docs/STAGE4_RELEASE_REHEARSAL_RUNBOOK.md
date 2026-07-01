# Stage 4 Release Rehearsal Runbook

This runbook fixes the evidence flow for Stage 4.1 Release-Gated Candidate.
Passing this flow is not Production Safe approval. It only makes Limited
Production rehearsal eligible for review.

## Canonical Inputs

- `logs/decisions.jsonl` is the canonical 30-day shadow evidence log.
- Every submitted shadow candidate must be represented by the `AuditEvent`
  lifecycle chain.
- `derived/bets.csv` is a report artifact regenerated from
  `logs/decisions.jsonl`; it is never authoritative.
- `.ci_latency.json` must include `p50`, `p95`, `p99`, `p999`,
  `timeout_rate`, and the approved `baseline_p99` when regression gating is
  being evaluated.
- `reports/stage4/replay_report.json` is required for release/rehearsal gates.
- `reports/stage4/critical_path_coverage.json` must contain branch coverage
  for the v2.2 critical path file set.
- `reports/stage4/feature_drift_report.json` records A7-3 top feature PSI and
  odds distribution PSI when a current comparison dataset is available.
- `data/market_snapshots/early_odds.csv` and
  `data/market_snapshots/closing_odds.csv` are required to build market
  dependency evidence that can pass Stage 4.

## Required Order

1. Complete a strict 30 calendar day shadow run with `SHADOW_MODE=1` and
   `SAFE_MODE=1`.
2. Regenerate the derived report:

```bash
python -m scripts.derive_bets_csv_from_decisions \
  --jsonl logs/decisions.jsonl \
  --csv derived/bets.csv
```

3. Merge real early/closing market snapshots:

```bash
python -m scripts.merge_market_snapshots \
  --base data/processed/historical_dataset.csv \
  --output data/processed/historical_dataset_with_market_snapshots.csv \
  --join-keys race_id,horse_id \
  --early-snapshot data/market_snapshots/early_odds.csv \
  --closing-snapshot data/market_snapshots/closing_odds.csv
```

4. Regenerate market dependency evidence:

```bash
python -m scripts.market_dependency_report \
  --input data/processed/historical_dataset_with_market_snapshots.csv \
  --outdir results/market_dependency \
  --strict
```

5. Run operator preflight drills in shadow/safe mode:

```bash
python -m scripts.stage4_operator_preflight_drills \
  --output-dir reports/stage4/preflight_drills \
  --status reports/stage4/preflight_status.json
```

6. Generate critical path branch coverage:

```bash
pytest -q \
  --cov=core \
  --cov=scripts.stage4_readiness_gate \
  --cov-branch \
  --cov-report=json:reports/stage4/critical_path_coverage.json
```

If this is shortened in CI for speed, keep
`tests/test_critical_path_coverage_gate.py` in the selected test list; it
contains the branch coverage guard cases for the critical path gate.

7. Build the Stage 4 evidence bundle:

```bash
python -m scripts.stage4_evidence_bundle \
  --decision-log logs/decisions.jsonl \
  --latency .ci_latency.json \
  --market-outdir results/market_dependency \
  --derived-bets derived/bets.csv \
  --coverage-json reports/stage4/critical_path_coverage.json \
  --input-replay-report reports/stage4/replay_report.json \
  --output-dir reports/stage4
```

8. Run the mandatory readiness gate:

```bash
python -m scripts.stage4_readiness_gate \
  --decision-log logs/decisions.jsonl \
  --latency .ci_latency.json \
  --market-outdir results/market_dependency \
  --derived-bets derived/bets.csv \
  --coverage-json reports/stage4/critical_path_coverage.json \
  --replay-report reports/stage4/replay_report.json \
  --require-replay-report \
  --output reports/stage4/readiness_gate.json
```

9. Review the Limited Production rehearsal preflight status:

```bash
python -m scripts.stage4_rehearsal_evidence \
  --historical-data data/processed/historical_dataset_with_market_snapshots.csv \
  --preflight-status reports/stage4/preflight_status.json
```

## Output Artifacts

- `reports/stage4/evidence_summary.json`
- `reports/stage4/readiness_gate.json`
- `reports/stage4/limited_production_rehearsal_preflight.json`
- `reports/stage4/critical_path_coverage.json`
- `reports/stage4/rehearsal_evidence_summary.json`
- `results/market_dependency/variant_summary.csv`
- `results/market_dependency/odds_regime_summary.csv`
- `results/market_dependency/race_class_summary.csv`
- `results/market_dependency/odds_perturbation_summary.csv`
- `derived/bets.csv`

## Market Dependency Review

The release gate requires `full`, `no_odds`, `market_only`, `early_odds_only`,
and `closing_odds` variants. `early_odds_only` being unavailable is
insufficient evidence and must fail. closing_odds is a contamination check,
not production feature proof.

The odds regime evidence must include `FAVORITE_HEAVY`, `LONGSHOT`, and
`DEEP_LONGSHOT` rows with `bets > 0` and numeric `roi_pct`.

`scripts.feature_drift_report` can generate the A7-3 PSI artifact:

```bash
python -m scripts.feature_drift_report \
  --baseline data/processed/historical_dataset.csv \
  --current data/processed/historical_dataset_with_market_snapshots.csv \
  --output reports/stage4/feature_drift_report.json
```

## Rehearsal Preconditions

`reports/stage4/readiness_gate.json` separates v2.2 failures into:

- `evidence_gate`: missing or insufficient proof, such as fewer than 30
  calendar shadow days, incomplete market dependency evidence, missing replay
  proof, missing audit hash fields, or missing coverage evidence.
- `metric_gate`: measured unsafe behavior, such as latency/timeout failure,
  replay mismatch, audit chain violation, governance lint violation, or branch
  coverage below 80%.

Limited Production rehearsal must not start unless all of these are true in
`reports/stage4/preflight_status.json`:

- `operator_kill_switch_tested`
- `manual_override_tested`
- `max_exposure_cap_enforced`
- `bankroll_reconciliation_tested`
- `tax_audit_export_reproduced`

Even if `reports/stage4/readiness_gate.json` has `passed = true`, this system
is still not Production Safe. Full production requires separate approval and
additional live evidence.

## Current Update Shortcut

After a real daily shadow append or after adding real market snapshot files,
run the current evidence refresh wrapper:

```bash
python -m scripts.stage4_current_update
```

The wrapper performs the current Stage 4 evidence refresh in the approved
order:

- regenerate `derived/bets.csv` from `logs/decisions.jsonl`
- regenerate `reports/stage4/replay_report.json`
- refresh `.ci_latency.json`
- merge real early/closing snapshots when both files exist
- regenerate market dependency evidence
- regenerate readiness, evidence bundle, rehearsal, survivability, and blocker
  summaries

If `data/market_snapshots/early_odds.csv` and
`data/market_snapshots/closing_odds.csv` are not both present, the wrapper uses
the base historical dataset and leaves the market snapshot blockers explicit.
It must not be used to fabricate or bypass `early_odds_only` or `closing_odds`
evidence.
