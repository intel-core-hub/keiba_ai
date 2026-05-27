**Adaptive Survival OS — Runbook (Safety-first quick guide)**

概要
-
この Runbook は本リポジトリを本番投入する前の最低限の安全ガードをまとめたものです。

重要な環境変数
-
- `DISABLE_META=1` — メタ/文明レイヤを無効化し、クリティカルパスへの重い依存を排除します。
- `IPAT_API_URL`, `IPAT_API_KEY` — 実運用時の賭け API 情報。

クリティカルガード（既実装）
-
- `core/low_latency_execution.py`:
  - 予測器呼び出しをスレッドプール経由で実行し、`timeout_sec` による打ち切りを行います。
  - `staleness_threshold` に基づき、古いオッズではノーベットを強制します。
  - `CircuitBreaker` により連続障害でクリティカルパスを遮断します。
- `core/predictor.py`:
  - 低レイテンシ向け `predict_raw(features)` を追加（Pandas を使わず NumPy 経由で推論）。
- `core/config_manager.py`:
  - 設定は `save_async()` でバックグラウンドにて原子書き込みされます。
- `core/meta_cognition.py`:
  - `DISABLE_META` を指定するとメタ処理は軽量モードになり I/O を行いません。
- `core/audit_hash_log.py`:
  - 監査ログに `sequence` と `monotonic_ns` を埋め込み、チェーン整合性を強化しました。

運用コマンド（例）
-
1. 仮想環境を有効化
```powershell
(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned)
& .venv\Scripts\Activate.ps1
```

2. セキュアなテスト（メタ無効化・クリティカルパス検証）
```powershell
$env:DISABLE_META = '1'
.venv\Scripts\python.exe scripts\test_critical_path.py
```

3. 安全な repomix の再生成（機密マスク済）
```powershell
.venv\Scripts\python.exe scripts\mask_and_run_repomix.py
```

本番導入にあたってのチェックリスト
-
1. `DISABLE_META` を有効化して、クリティカルパスでメタ処理がロードされないことを確認する。
2. `staleness_threshold` を運用に合わせて調整（推奨 1.0〜3.0 秒）。
3. リスク設定（`max_fraction` 等）をロックダウンし、本番中の自動リフィットは無効化すること。
4. 監査ログのバックアップとリモートコピー（WORM ストレージ）を確立すること。
5. 本番はステージングで 48 時間以上の負荷試験を実施後に限定リリースする。

連絡先
-
システム責任者: Principal Systems Architect

定期負荷試験（スケジュール）
-
- ワークフロー: `.github/workflows/staging_load_test.yml` が追加されています。デフォルトは毎日03:00 UTCで実行され、`DISABLE_META=1` が設定されます。
- キャッシュ: `actions/cache@v4` による pip キャッシュを利用し、依存インストールを高速化します。
- アーティファクト保持: レポートは 30 日間保持されます（`retention-days: 30`）。

手動トリガーと検証手順
-
1. GitHub 上で手動トリガー: Actions → "Staging Load Test" → Run workflow を選択して起動します。入力パラメータで `concurrency` / `requests_per_worker` を調整できます。
2. CLI からディスパッチ（オプション）:
  - `gh` CLI を使う場合:
```bash
gh workflow run staging_load_test.yml --ref main --field concurrency=10 --field requests_per_worker=10
```
3. ローカル実行（検証）例:
```powershell
$env:DISABLE_META='1'
.venv\Scripts\python.exe -m scripts.load_test 10 10
```
4. 成果物の確認:
  - ワークフロー実行後、Actions の実行ページから `load-test-reports` アーティファクトをダウンロードして内容を確認してください。
  - ローカルでは `reports/` に出力されます。例: `reports/load_test_<timestamp>.json` / `.csv` / `.png`。

運用メモ
-
- cron の時刻や保持期間は ` .github/workflows/staging_load_test.yml ` を編集して変更してください。
- ステージング環境で外部エンドポイント（IPAT 等）に接続する場合は、機密情報が含まれないテストデータを使用するか、エンドポイントをモックしてください。

この Runbook の該当項目を更新済み: スケジュール、キャッシュ、アーティファクト保持、検証手順。
