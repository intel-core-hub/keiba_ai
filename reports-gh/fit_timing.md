# Fit Timing Analysis

## Where preprocessing is fit

- `learning/model_factory.py::build_boosted_pipeline`
  - Pipeline contains `SimpleImputer` and optional `StandardScaler`.
  - These are fit when `pipeline.fit(X_train, y_train)` が呼ばれる。

- `validation/walk_forward_validation.py::_train_safe_model`
  - `base_model = self._build_model()` は `Pipeline([imputer, scaler, model])` を返す。
  - `base_model.fit(X_base, y_base)` により imputer/scaler は `X_base` のみで fit される（正しい）。
  - Calibration は `CalibratedClassifierCV(..., cv='prefit')` を `X_cal` のみで fit している（正しい）。

- `core/prediction/predictor.py::train`
  - `train_test_split(..., shuffle=False)` により時系列分割している。
  - `self.model.fit(X_train, y_train)` によりパイプライン内の imputer/scaler は `X_train` のみで fit される（正しい）。

## 以前の leakage 点（対処済）
- `data/historical_dataset.py::finalize()` が全データの中央値で数値補完していた → グローバル統計が訓練に漏れていた（修正済）。
- `feature_engineering` における全体 min/max 正規化により全データ統計を使用していた → 修正済。

## 推奨チェックリスト（CI）
- モデル学習前に、`X_train` に対してのみ `imputer/scaler` が `fit` されていることを自動検査するテストを追加する。
- データ加工パイプラインが `chronological_sort` → `per-horse groupby shift/rolling` を順守していることを lint/検査する。

