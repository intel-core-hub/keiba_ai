# Degradation Mode

Degradation Mode is the Survival OS automatic shrink-down layer. It is not a profit maximizer. It protects the system when data quality, capital stress, runtime latency, drift, or safety violations deteriorate.

## Modes

| Mode | Meaning | Execution posture |
|---|---|---|
| NORMAL | All survival signals are healthy | production candidates only: win, place, wide |
| WARNING | Early deterioration | same bet types, half stake, narrower coverage |
| DANGER | Material deterioration | win/place only, quarter stake, operator acknowledgement required |
| CRITICAL | Unsafe | force no bet, fail closed, operator acknowledgement required |

## Input Signals

The evaluator uses data quality (`data_quality_score`, missing/stale odds, missing features), loss/capital stress (`loss_streak`, `drawdown_pct`), runtime stress (`latency_p99_ms`, `latency_regression_rate`, `timeout_rate`), drift (`drift_gap50`, `feature_psi_max`, `odds_distribution_psi`), and safety violations (`shadow_only_violation_count`, `disabled_bet_type_candidate_count`).

## Thresholds

Thresholds live in `config/degradation_mode.yaml`. The default policy is intentionally conservative:

- WARNING starts at data quality below `0.95`, drawdown at least `5%`, p99 latency at least `50ms`, latency regression at least `15%`, or drift PSI/gap deterioration.
- DANGER starts at data quality below `0.90`, drawdown at least `10%`, loss streak at least `8`, p99 latency at least `100ms`, latency regression at least `30%`, or stronger drift.
- CRITICAL starts on any timeout, data quality below `0.80`, drawdown at least `15%`, loss streak at least `12`, shadow-only execution violation, or disabled bet type candidate.

## Bet Types

Degradation Mode can only tighten the current v2.3 bet type policy:

- Production candidates: `win`, `place`, `wide`
- Shadow-only: `quinella`, `trio`
- Disabled: `exacta`, `trifecta`

It must never promote shadow-only bet types to live execution and must never re-enable disabled bet types. `DANGER` removes `wide`; `CRITICAL` removes all bet types.

## Force No Bet

`force_no_bet=true` means evaluation can be logged, but execution submit is prohibited. The executor records the degradation mode and reason, then blocks before submit.

## Operator Acknowledgement

`requires_operator_ack=true` means the system is not healthy enough for unattended progression. `DANGER` and `CRITICAL` require explicit operator review before normal operation resumes.

## Fail Closed

When Degradation Mode cannot safely decide, the expected behavior is to shrink or stop. It should never fail open into broader coverage, larger stake, shadow-only live submit, or disabled bet type activation.

## Stage 4 Integration

`scripts/degradation_mode_report.py` produces:

- `reports/stage4/degradation_mode_report.json`
- `reports/stage4/degradation_mode_report.csv`

The Stage 4 evidence bundle records the report path, critical count, force-no-bet count, restrict count, and recommendation. The v2.3 rubric report includes observed mode rates and treats repeated CRITICAL or persistent force-no-bet as release blockers.

## Do Not

- Ignore degradation signals.
- Send `shadow_only` bet types to live execution.
- Re-enable disabled bet types.
- Silently continue through CRITICAL.
- Treat this layer as a profit optimizer.
