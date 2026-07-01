# Keiba AI / Survival OS Evaluation Rubric v2.3

## v2.2 からの変更点

v2.3 は v2.2 の Evidence Gate / Metric Gate 分離、A2/A7 責務分離、CI 自動判定を維持しつつ、馬券種拡張に対応する。中心変更は、`bet_type` 別の ROI / Profit Factor / Hit Rate / DD 寄与 / Coverage / HHI を評価対象に加え、Bet Type Gate を Metric Gate 内に追加することである。

Stage 4 必須証跡として `reports/stage4/bet_type_metrics.json` を追加する。旧単勝形式は `bet_type=win`、`legs=[horse_id or selection_id]` として後方互換変換できなければ Evidence Gate 未通過とする。

## 馬券種の運用区分

| bet_type | 日本語名 | 区分 | 本番実賭け | Shadow 評価 | ordered | legs |
|---|---|---|---|---|---:|---:|
| win | 単勝 | production_candidate | 可 | 可 | false | 1 |
| place | 複勝 | production_candidate | 可 | 可 | false | 1 |
| wide | ワイド | production_candidate | 可 | 可 | false | 2 |
| quinella | 馬連 | shadow_only | 不可 | 可 | false | 2 |
| trio | 三連複 | shadow_only | 不可 | 可 | false | 3 |
| exacta | 馬単 | disabled | 不可 | 不可 | true | 2 |
| trifecta | 三連単 | disabled | 不可 | 不可 | true | 3 |

`win` / `place` / `wide` は本番候補だが、bet_type 別の A2/A3/A7 に C が出た場合は当該馬券種を本番候補から除外する。`quinella` / `trio` は評価には残すが、実賭け経路、IPAT 送信、production bet executor に渡してはならない。`exacta` / `trifecta` は candidate / decision / execution のいずれにも出してはならない。

## Bet Type Gate

Bet Type Gate は Metric Gate 内の即時失格判定として扱う。以下の条件を満たす必要がある。

| 項目 | 合格基準 |
|---|---|
| production_candidate_bet_types | `win`, `place`, `wide` |
| shadow_only_bet_types | `quinella`, `trio` |
| disabled_bet_types | `exacta`, `trifecta` |
| shadow_only_violation_count | 0 |
| disabled_bet_type_candidate_count | 0 |
| production_execution_unknown_bet_type_count | 0 |
| bet_type_metrics_path | `reports/stage4/bet_type_metrics.json` が存在 |
| old win compatibility | `horse_id` / `selection_id` から `win` に変換可能 |

## Gate 0: Evidence Gate 追加条件

以下は Evidence Gate 未通過とする。

- `bet_type` 欠損かつ旧 win 形式へ変換不能
- `bet_type_metrics.json` 不足
- bet_type 別メトリクスが算出不能

## Gate 1: Metric Gate 即時失格条件

以下は総合スコアを問わず Metric Gate 失格とする。

- `shadow_only` の馬券種が実賭け経路に入った
- disabled の馬券種が candidate / decision に出た
- `production_candidate=false` が execution submit に渡った
- bet_type 別 exposure limit を超過した

## bet_type 別 A2 / A3 / A7 評価

A2 は bet_type 別 ROI、Profit Factor、Hit Rate、worst fold ROI、stake_sum、profit_sum を評価する。production_candidate に C が出た場合は当該 bet_type を本番候補から除外する。shadow_only に C が出た場合は disabled 候補とする。

A3 は bet_type 別 DD 寄与、exposure_share、`max_combinations_per_race`、`max_race_exposure_share`、shadow_only 実賭け除外、disabled 除外を評価する。shadow_only 実賭け混入と disabled 出現は 1 件でも即失格とする。

A7 は bet_type 別 Coverage、HHI、OOS stability、Regime ROI、Drift 影響を評価する。Coverage は 1% 未満または 50% 超で C とし、HHI は 0.60 以上で C とする。

## Shadow Only Recommendation

`quinella` / `trio` は 30 日 Shadow 後に以下の recommendation を出す。

| recommendation | 条件 |
|---|---|
| disable | ROI < -5%、Profit Factor < 0.95、DD 寄与が閾値超過、Coverage < 1% または > 50%、HHI >= 0.60、RiskClamp 拒否頻発 |
| keep_shadow | 明確な優位性はないが危険でもない、またはサンプル不足 |
| promote_candidate_possible | ROI >= 0、Profit Factor >= 1.05、A7 に C なし、DD 寄与が小さい、Coverage 正常、OOS 安定 |

`promote_candidate_possible` は即本番昇格を意味しない。追加 Shadow と手動レビューを必須とする。

## Stage 4 必須証跡

v2.3 の evidence summary には最低限以下を含める。

- `bet_type_metrics_path`
- `production_candidate_bet_types`
- `shadow_only_bet_types`
- `disabled_bet_types`
- `shadow_only_violation_count`
- `disabled_bet_type_candidate_count`
- `production_execution_unknown_bet_type_count`
- `bet_type_missing_count`
- `old_win_compat_conversion_count`

## Survival OS 方針

Survival OS は収益性より生存性を優先する。馬券種を増やしても、shadow_only は評価に残すだけで実賭けしない。disabled は候補にも出さない。全体スコアが良くても、馬券種別 Metric Gate 違反があれば投入不可とする。曖昧な実装は fail-open ではなく fail-closed とする。
