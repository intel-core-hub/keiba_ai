# Leakage Risk Report

## 概要
本レポートはリポジトリ全体を静的監査し、未来情報リーク（data leakage）のリスクがある箇所を特定・修正した記録です。重要な修正は `data/historical_dataset.py` に対するものです。

## 主要所見（高リスク）
- `feature_engineering`: `last_finish` が全体 `shift(1)` で算出されていたため、行順次第で別馬や未来情報を参照するリスクがありました。修正済み（馬ごとの groupby + shift を使用）。
- `feature_engineering`: `avg_finish_last5` および `avg_speed_index_last5` が外部ソースから与えられていた場合、将来集約値（future aggregates）をそのまま使用していました。修正済み（馬ごとの過去のみから再計算）。
- グローバル正規化: `speed_index` をデータ全体の min/max で正規化していた（未来情報を含む統計）。修正済み（グローバル正規化を削除し、モデル側のスケーラに委譲）。
- グローバル補完: `finalize()` が数値列に対してデータセット全体の中央値で補完していたため、将来の統計が訓練に漏れていました。修正済み（数値 NaN は残し、パイプラインの `SimpleImputer` に委譲）。

## 中リスクの所見
- `Predictor.train` と `WalkForwardValidator` は概ね時系列分割（shuffle=False、race-based blocks）を利用しており、calibration のフィッティングも訓練領域内で行われる設計でした。ただし、事前に全体データで計算された特徴量（avg_* や正規化）があれば、その安全性が担保されない点に注意。これを防ぐため、上記修正を実施しました。

## 疑わしい特徴量（要確認）
- popularity, final_odds, closing_odds, payout, post-race 由来のカラム
- `avg_finish_last5`, `avg_speed_index_last5`（外部提供時）
- `finishing_position` を使った派生量（集計方法の確認が必要）

## フィットタイミングのチェック結果
- モデルパイプライン内の `SimpleImputer` / `StandardScaler` は訓練データに対してのみ `fit` される実装（`WalkForwardValidator._train_safe_model`、`build_boosted_pipeline` 内の pipeline）。
- ただし、データ前処理段階で行ったグローバル統計（旧 finalize、旧 speed_index normalization 等）は修正が必要でした（対応済み）。

## 推奨修正（既実装分）
- `data/historical_dataset.py`:
  - chronological_sort を feature_engineering 前に移動（修正済）
  - per-horse groupby + shift/rolling による `last_finish` / `avg_*_last5` の再計算（修正済）
  - グローバル min/max 正規化の削除（修正済）
  - global median による数値補完の削除（修正済）

## 追加提案（運用／改善）
- データ受領パイプラインで、raw に `avg_*` や `final_odds` のような将来集約値が含まれていないかを検査するバリデータを導入する。発見時は自動的に再計算または除外するポリシーを適用する。
- 特徴量作成は必ず「時系列ソート → グループ集計（過去のみ） → 保存」の順で行うように CI チェックを追加する。
- モデル訓練スクリプトに対し、データセットのメタ情報（何を再計算したか、何を外部で与えたか）をログに残す。

## 変更点一覧（コミット済）
- `data/historical_dataset.py`:
  - chronological_sort の順序変更
  - per-horse shift/rolling 計算
  - global normalization 削除
  - finalize() のグローバル補完削除

## 次のステップ
1. テスト用の小規模 walk-forward を実行して、修正後特徴量が意図通り過去情報のみを参照していることを確認してください（私が代行可能）。
2. raw CSV 監査スクリプト（`scripts/audit_raw_features.py`）を追加して、将来集約値や final odds の存在を検出して自動通知することを推奨します。

