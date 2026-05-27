# scripts/monthly_retrain.py
#
# 月次再学習スクリプト
#
# 使い方:
#   python scripts/monthly_retrain.py
#   python scripts/monthly_retrain.py --month 2024-12
#   python scripts/monthly_retrain.py --window 6        # 直近6ヶ月分のみ使用
#   python scripts/monthly_retrain.py --dry-run         # 学習のみ、モデル保存しない

import argparse
import json
import logging
import os
import sys
from datetime import datetime, date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.metrics import brier_score_loss, log_loss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.uncertainty import build_uncertainty_profile
from learning.model_factory import build_boosted_pipeline, build_logistic_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# =====================================================
# 設定
# =====================================================

DATASET_PATH   = "data/processed/historical_dataset.csv"
MODEL_PATH     = "models/prediction_model.pkl"
METRICS_LOG    = "models/retrain_log.jsonl"
FEATURE_COLS   = [
    "odds",
    "favorite_rank",
    "weight_carried",
    "age",
    "horse_weight",
    "horse_weight_diff",
    "avg_finish_last5",
    "avg_finish_last3",
    "avg_speed_index_last5",
    "recent_form_score",
    "last_finish",
    "rest_days",
]
TARGET_COL = "target_win"

# Calibration gap がこの値を超えたら再学習を強く推奨
CALIBRATION_WARN_THRESHOLD = 0.005


# =====================================================
# 引数パース
# =====================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="月次再学習スクリプト"
    )
    parser.add_argument(
        "--model",
        choices=("boosted", "logistic"),
        default="boosted",
        help="学習するモデル種別（boosted=LightGBM系, logistic=既存基準）",
    )
    parser.add_argument(
        "--month",
        default=None,
        help="再学習基準月（YYYY-MM）。省略時は当月。",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=None,
        help="学習に使う直近N ヶ月（例: 6 → 直近6ヶ月のみ）。省略時は全データ。",
    )
    parser.add_argument(
        "--dataset",
        default=DATASET_PATH,
        help="データセットパス",
    )
    parser.add_argument(
        "--model-out",
        default=MODEL_PATH,
        dest="model_out",
        help="モデル出力パス",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="学習・評価のみ実行。モデルを保存しない。",
    )
    return parser.parse_args()


# =====================================================
# データ読み込み・フィルタ
# =====================================================

def load_dataset(path: str, window_months: int | None) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)

    # race_date が有効な行のみ使用（地方競馬を除外）
    def is_valid_date(d):
        s = str(d)
        if len(s) != 8 or not s.isdigit():
            return False
        month = int(s[4:6])
        day   = int(s[6:8])
        return 1 <= month <= 12 and 1 <= day <= 31

    if "race_date" in df.columns:
        valid_mask = df["race_date"].apply(is_valid_date)
        before = len(df)
        df = df[valid_mask].reset_index(drop=True)
        logger.info("地方競馬除外: %d → %d行", before, len(df))

    df = df.sort_values("race_date").reset_index(drop=True)

    # window 指定がある場合は直近 N ヶ月のみ
    if window_months is not None and "race_date" in df.columns:
        latest = df["race_date"].max()
        # YYYYMMDD → 年月計算
        latest_year  = int(str(latest)[:4])
        latest_month = int(str(latest)[4:6])

        cutoff_year  = latest_year - (window_months // 12)
        cutoff_month = latest_month - (window_months % 12)
        if cutoff_month <= 0:
            cutoff_month += 12
            cutoff_year  -= 1

        cutoff = f"{cutoff_year}{cutoff_month:02d}01"
        before = len(df)
        df = df[df["race_date"].astype(str) >= cutoff].reset_index(drop=True)
        logger.info(
            "直近%dヶ月フィルタ（%s以降）: %d → %d行",
            window_months, cutoff, before, len(df),
        )

    logger.info(
        "学習データ: %d行, 期間 %s 〜 %s",
        len(df),
        df["race_date"].iloc[0] if len(df) > 0 else "N/A",
        df["race_date"].iloc[-1] if len(df) > 0 else "N/A",
    )
    return df


# =====================================================
# モデル構築
# =====================================================

def build_model(model_kind: str) -> Pipeline:
    if model_kind == "logistic":
        return build_logistic_pipeline(
            cv=3,
            calibrated=True,
        )

    return build_boosted_pipeline(
        cv=3,
        calibrated=True,
        use_scaler=False,
    )


# =====================================================
# 学習・評価
# =====================================================

def train_and_evaluate(df: pd.DataFrame, model_kind: str) -> dict:
    feat_cols = [c for c in FEATURE_COLS if c in df.columns]
    missing   = [c for c in FEATURE_COLS if c not in df.columns]
    if missing:
        logger.warning("特徴量不足: %s", missing)

    X = df[feat_cols].values
    y = df[TARGET_COL].values

    # 時系列分割（シャッフルなし）
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    logger.info(
        "学習: %d行 / 評価: %d行", len(X_train), len(X_test)
    )

    model = build_model(model_kind)
    model.fit(X_train, y_train)

    proba = model.predict_proba(X_test)[:, 1]

    brier   = round(float(brier_score_loss(y_test, proba)), 4)
    ll      = round(float(log_loss(y_test, proba)), 4)
    cal_gap = round(float(abs(proba.mean() - y_test.mean())), 4)
    uncertainty_profile = build_uncertainty_profile(
        probabilities=proba,
        hits=y_test,
        bins=10,
        bootstrap_samples=200,
    )

    # drift: 前半と後半の予測確率の差
    mid   = len(proba) // 2
    drift = round(float(abs(proba[:mid].mean() - proba[mid:].mean())), 4)

    metrics = {
        "model_kind":     model_kind,
        "brier":           brier,
        "log_loss":        ll,
        "calibration_gap": cal_gap,
        "prediction_drift": drift,
        "uncertainty_profile": uncertainty_profile,
        "recommended_max_uncertainty": uncertainty_profile.get("recommended_max_uncertainty", 0.65),
        "train_rows":      int(len(X_train)),
        "test_rows":       int(len(X_test)),
        "features":        feat_cols,
    }

    return model, metrics


# =====================================================
# モデル保存
# =====================================================

def save_model(
    model,
    metrics: dict,
    model_out: str,
    target_month: str,
) -> None:
    out_path = Path(model_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # バージョン付きバックアップ
    if out_path.exists():
        backup = out_path.with_suffix(f".{target_month}.bak.pkl")
        import shutil
        shutil.copy2(out_path, backup)
        logger.info("バックアップ: %s", backup)

    payload = {
        "model":          model,
        "model_kind":     metrics.get("model_kind", "boosted"),
        "features":       metrics["features"],
        "trained_month":  target_month,
        "trained_at":     datetime.now().isoformat(),
        "metrics":        metrics,
        "uncertainty_profile": metrics.get("uncertainty_profile", {}),
    }
    joblib.dump(payload, out_path)
    logger.info("モデル保存: %s", out_path)


# =====================================================
# メトリクスログ
# =====================================================

def log_metrics(metrics: dict, target_month: str) -> None:
    record = {
        "month":     target_month,
        "timestamp": datetime.now().isoformat(),
        **metrics,
    }
    log_path = Path(METRICS_LOG)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("メトリクスログ追記: %s", log_path)


def load_metrics_log() -> list[dict]:
    log_path = Path(METRICS_LOG)
    if not log_path.exists():
        return []
    records = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# =====================================================
# Calibration drift の判定
# =====================================================

def check_calibration_drift(metrics: dict, history: list[dict]) -> None:
    cal = metrics["calibration_gap"]

    if cal > CALIBRATION_WARN_THRESHOLD:
        logger.warning(
            "⚠️  Calibration gap %.4f > %.4f — 再学習を推奨",
            cal, CALIBRATION_WARN_THRESHOLD,
        )
    else:
        logger.info("✅ Calibration gap %.4f — 正常範囲", cal)

    # 直近3回の推移を表示
    if len(history) >= 2:
        recent = history[-3:]
        logger.info("Calibration gap の推移:")
        for r in recent:
            logger.info(
                "  %s: %.4f", r.get("month", "?"), r.get("calibration_gap", 0)
            )


# =====================================================
# メイン
# =====================================================

def print_report(metrics: dict, target_month: str, dry_run: bool) -> None:
    print()
    print("=" * 55)
    print(f"  月次再学習レポート  [{target_month}]")
    if dry_run:
        print("  ※ DRY RUN — モデルは保存されていません")
    print("=" * 55)
    print(f"  学習行数:          {metrics['train_rows']:,}")
    print(f"  評価行数:          {metrics['test_rows']:,}")
    print(f"  使用特徴量:        {len(metrics['features'])} 列")
    print(f"  モデル種別:        {metrics.get('model_kind', 'boosted')}")
    print()
    print("  【精度指標】")
    print(f"    Brier score:     {metrics['brier']}  (ランダム≈0.083)")
    print(f"    Log loss:        {metrics['log_loss']}")

    cal = metrics["calibration_gap"]
    cal_mark = "✅" if cal <= CALIBRATION_WARN_THRESHOLD else "⚠️ "
    print(f"    Calibration gap: {cal}  {cal_mark}")
    print(f"    Prediction drift:{metrics['prediction_drift']}")
    print(f"    Recommended uncertainty threshold: {metrics.get('recommended_max_uncertainty', 0.65)}")
    print("=" * 55)


def main() -> None:
    args = parse_args()

    # 対象月の決定
    if args.month:
        target_month = args.month  # "YYYY-MM"
    else:
        today = date.today()
        target_month = f"{today.year}-{today.month:02d}"

    logger.info("対象月: %s", target_month)
    logger.info("モード: %s", "DRY RUN" if args.dry_run else "本番")
    if args.window:
        logger.info("学習窓: 直近%dヶ月", args.window)

    # データ読み込み
    df = load_dataset(args.dataset, args.window)
    if len(df) < 100:
        logger.error("データが少なすぎます（%d行）。終了します。", len(df))
        sys.exit(1)

    # 学習・評価
    logger.info("学習開始...")
    model, metrics = train_and_evaluate(df, args.model)

    # 履歴ログ読み込み（drift 判定用）
    history = load_metrics_log()
    check_calibration_drift(metrics, history)

    # レポート表示
    print_report(metrics, target_month, args.dry_run)

    if args.dry_run:
        logger.info("DRY RUN のためモデル保存をスキップ")
        return

    # モデル保存
    save_model(model, metrics, args.model_out, target_month)

    # メトリクスログ
    log_metrics(metrics, target_month)

    logger.info("完了 ✅")


if __name__ == "__main__":
    main()
