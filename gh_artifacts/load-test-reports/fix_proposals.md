# Fix Proposals & Corrected Implementation

## 1) 実装済み（本コミット）
- `data/historical_dataset.py`:
  - chronological_sort を feature_engineering 前に移動
  - per-horse groupby + shift + rolling による `last_finish`, `avg_finish_last5`, `avg_speed_index_last5` の再計算
  - グローバル min/max 正規化の削除
  - finalize() による全データ中央値での補完を停止

これらにより、代表的な future-leakage パターンを除去しました。

## 2) 追加で推奨する修正
- Raw CSV の監査: `scripts/audit_raw_features.py` を CI で実行し、`final_odds` や `avg_*_last5` 等の存在を検出した場合は自動アラート/除外する。
- Feature provenance: 各特徴量が "再計算済み" か "外部提供" かを示すメタ列を保存する（例: `avg_finish_last5_source` 列）。
- Unit tests: 小規模の walk‑forward テストを用意し、修正前後で特徴量が未来情報を参照していないことを確認するテストを導入する。
- CI ルール: データ処理シーケンスが `extract_date -> sort -> per-horse agg -> finalize` の順になっていることを検査する linter を追加。

## 3) 運用上の注意
- Odds: `odds` 列がいつ記録されたか（最終オッズか、出馬表公開時のオッズか）を明示してください。終盤の変動を取り込むとマーケット情報リークにつながる可能性があります。
- Calibration: キャリブレーション（Brier/ECE）を算出する際は、必ず訓練領域／キャリブレーション領域内でのみ計算すること。既存の `WalkForwardValidator` は適切に分離しています。

