# scripts/walk_forward_eval.py
#
# 収集済みデータで walk-forward 検証と ROI 計算を行う。
#
# 使い方:
#   python scripts/walk_forward_eval.py
#   python scripts/walk_forward_eval.py --dataset data/processed/historical_dataset.csv
#   python scripts/walk_forward_eval.py --train-ratio 0.7

import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.model_factory import build_boosted_pipeline, build_logistic_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 学習に使う特徴量（null が多い列は除外済み）
FEATURE_COLS = [
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Walk-forward 検証と ROI 計算")
    parser.add_argument(
        "--dataset",
        default="data/processed/historical_dataset.csv",
        help="学習済みデータセットのパス",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.7,
        help="学習データの割合（0〜1）。残りが検証データ。",
    )
    parser.add_argument(
        "--model",
        choices=("boosted", "logistic"),
        default="boosted",
        help="検証に使うモデル（boosted=LightGBM系, logistic=既存基準）",
    )
    parser.add_argument(
        "--kelly-fraction",
        type=float,
        default=0.1,
        help="Kelly 基準の分数（0.1=10%%）。投資額の上限に使用。",
    )
    parser.add_argument(
        "--jra-only",
        action="store_true",
        default=False,
        dest="jra_only",
    )
    return parser.parse_args()


def load_and_sort(path: str, jra_only: bool = False) -> pd.DataFrame:
    """データセットを読み込み時系列順にソートする。"""
    needed_columns = set(FEATURE_COLS) | {TARGET_COL, "race_id", "race_date"}
    df = pd.read_csv(
        path,
        usecols=lambda col: col in needed_columns,
        engine="python",
    )

    # race_date がなければ race_id の先頭8桁から復元
    if "race_date" not in df.columns:
        df["race_date"] = df["race_id"].astype(str).str[:8]
        logger.info("race_date を race_id から復元しました")

    # 無効な race_date（地方競馬等）を除外
    def is_valid_date(d):
        s = str(d)
        if len(s) != 8 or not s.isdigit():
            return False
        month = int(s[4:6])
        day   = int(s[6:8])
        return 1 <= month <= 12 and 1 <= day <= 31

    valid_mask = df["race_date"].apply(is_valid_date)
    invalid_count = (~valid_mask).sum()
    if invalid_count > 0:
        logger.info("無効 race_date（地方競馬等）を除外: %d行", invalid_count)
        df = df[valid_mask].reset_index(drop=True)

    if jra_only:
        logger.info("--jra-only: 地方競馬を除外済み（%d行）", len(df))

    df = df.sort_values("race_date").reset_index(drop=True)
    logger.info(
        "データ: %d行, 期間 %s 〜 %s",
        len(df),
        df["race_date"].iloc[0],
        df["race_date"].iloc[-1],
    )
    return df


def expected_calibration_error(y_true: np.ndarray, proba: np.ndarray, n_bins: int = 10) -> float:
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_ids = np.clip(np.digitize(proba, bins, right=True) - 1, 0, n_bins - 1)
    ece = 0.0
    total = len(proba)

    for idx in range(n_bins):
        mask = bin_ids == idx
        if not np.any(mask):
            continue
        bin_prob = proba[mask].mean()
        bin_acc = y_true[mask].mean()
        weight = mask.sum() / total
        ece += abs(bin_prob - bin_acc) * weight

    return round(float(ece), 4)


def build_model(model_kind: str, cv: int, calibrated: bool):
    if model_kind == "logistic":
        return build_logistic_pipeline(cv=cv, calibrated=calibrated)

    return build_boosted_pipeline(cv=cv, calibrated=calibrated, use_scaler=False)


def evaluate(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    kelly_fraction: float,
    model_kind: str,
) -> dict:
    """
    学習・検証を実行して各種指標を返す。

    指標:
      brier_score     : 予測精度（低いほど良い）
      calibration_gap : |平均予測確率 - 実際勝率|
      roi_flat        : 均等買い（全馬同額）の回収率
      roi_kelly       : Kelly 基準（期待値 > 1 の馬のみ）の回収率
      hit_rate        : 最高確率馬の的中率
      positive_ev_pct : 期待値 > 1.0 の馬の割合
    """
    feat_cols = [c for c in FEATURE_COLS if c in df_train.columns]
    missing = [c for c in FEATURE_COLS if c not in df_train.columns]
    if missing:
        logger.warning("特徴量が不足: %s", missing)

    X_train = df_train[feat_cols].copy()
    y_train = df_train[TARGET_COL].values
    X_test  = df_test[feat_cols].copy()
    y_test  = df_test[TARGET_COL].values

    class_counts = pd.Series(y_train).value_counts()
    min_class_count = int(class_counts.min()) if not class_counts.empty else 0
    calibrated = min_class_count >= 2 and len(X_train) >= 6
    cv_folds = max(2, min(3, min_class_count)) if calibrated else 2

    model = build_model(model_kind, cv=cv_folds, calibrated=calibrated)
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)[:, 1]

    # --- 基本指標 ---
    brier = round(brier_score_loss(y_test, proba), 4)
    ll    = round(log_loss(y_test, proba, labels=[0, 1]), 4)
    cal_gap = round(abs(proba.mean() - y_test.mean()), 4)
    ece = expected_calibration_error(np.asarray(y_test), np.asarray(proba), n_bins=10)

    # --- ROI 計算 ---
    df_eval = df_test.copy()
    df_eval["pred_prob"] = proba

    # オッズ列の確認
    has_odds = "odds" in df_eval.columns

    roi_flat  = None
    roi_kelly = None
    hit_rate  = None
    pos_ev    = None

    if has_odds:
        df_eval["odds_num"] = pd.to_numeric(df_eval["odds"], errors="coerce")

        # レースごとに最高確率の馬を1頭選ぶ（単勝1点買い）
        race_groups = df_eval.groupby("race_id")
        flat_returns  = []
        kelly_returns = []
        hits = []

        for race_id, group in race_groups:
            group = group.dropna(subset=["odds_num"])
            if group.empty:
                continue

            # 最高確率の馬
            top = group.loc[group["pred_prob"].idxmax()]
            actual_win = int(top[TARGET_COL])
            odds_val   = float(top["odds_num"])

            # 均等買い: 常に1点 = 1単位
            flat_returns.append(odds_val if actual_win else -1.0)
            hits.append(actual_win)

            # Kelly 買い: 期待値 > 1.0 の場合のみ
            ev = top["pred_prob"] * odds_val
            if ev > 1.0:
                # フラクショナル Kelly: stake = fraction * (p*o - 1) / (o - 1)
                stake = kelly_fraction * (
                    (top["pred_prob"] * odds_val - 1) / (odds_val - 1)
                )
                stake = max(0.01, min(stake, 1.0))  # 1〜100%の範囲
                pnl = (odds_val - 1) * stake if actual_win else -stake
                kelly_returns.append(pnl)

        if flat_returns:
            total_bet = len(flat_returns)
            roi_flat  = round((sum(flat_returns) / total_bet + 1) * 100, 1)
            hit_rate  = round(sum(hits) / len(hits) * 100, 1)

        if kelly_returns:
            roi_kelly = round((sum(kelly_returns) / len(kelly_returns) + 1) * 100, 1)

        # 期待値 > 1.0 の馬の割合
        ev_series = df_eval["pred_prob"] * df_eval["odds_num"]
        pos_ev = round((ev_series > 1.0).mean() * 100, 1)

    return {
        "train_rows":     len(df_train),
        "test_rows":      len(df_test),
        "train_period":   f"{df_train['race_date'].iloc[0]} 〜 {df_train['race_date'].iloc[-1]}",
        "test_period":    f"{df_test['race_date'].iloc[0]} 〜 {df_test['race_date'].iloc[-1]}",
        "brier_score":    brier,
        "log_loss":       ll,
        "calibration_gap": cal_gap,
        "ece":            ece,
        "roi_flat":       roi_flat,
        "roi_kelly":      roi_kelly,
        "hit_rate":       hit_rate,
        "positive_ev_pct": pos_ev,
        "features_used":  len(feat_cols),
        "model_kind":     model_kind,
    }


def print_report(result: dict) -> None:
    print()
    print("=" * 55)
    print("  Walk-Forward 検証レポート")
    print("=" * 55)
    print(f"  学習期間: {result['train_period']}")
    print(f"  検証期間: {result['test_period']}")
    print(f"  学習行数: {result['train_rows']:,}  検証行数: {result['test_rows']:,}")
    print(f"  モデル: {result['model_kind']}")
    print(f"  使用特徴量: {result['features_used']} 列")
    print()
    print("  【予測精度】")
    print(f"    Brier score:     {result['brier_score']}  (低いほど良い、ランダム≈0.083)")
    print(f"    Log loss:        {result['log_loss']}")
    print(f"    Calibration gap: {result['calibration_gap']}  (0 が理想)")
    print(f"    ECE:             {result['ece']}  (0 が理想)")
    print()
    print("  【回収率シミュレーション（単勝1点買い）】")
    if result["roi_flat"] is not None:
        flat_marker = "✅" if result["roi_flat"] >= 75 else "  "
        print(f"    均等買い ROI:    {result['roi_flat']}%  {flat_marker}")
        print(f"    的中率:          {result['hit_rate']}%")
        print(f"    期待値>1の馬:    {result['positive_ev_pct']}%")
    if result["roi_kelly"] is not None:
        kelly_marker = "✅" if result["roi_kelly"] >= 80 else "  "
        print(f"    Kelly 買い ROI:  {result['roi_kelly']}%  {kelly_marker}")
    print()
    print("  ※ 競馬の控除率は約25%。ROI 75%以上なら平均的な水準。")
    print("     ROI 100%以上で黒字。")
    print("=" * 55)


def main() -> None:
    args = parse_args()

    logger.info("データ読み込み: %s", args.dataset)
    df = load_and_sort(args.dataset, jra_only=args.jra_only)

    # 時系列分割（シャッフルしない）
    split_idx = int(len(df) * args.train_ratio)
    df_train = df.iloc[:split_idx].copy()
    df_test  = df.iloc[split_idx:].copy()

    logger.info(
        "分割: 学習 %d行 / 検証 %d行 (train_ratio=%.0f%%)",
        len(df_train), len(df_test), args.train_ratio * 100,
    )

    logger.info("学習・評価中...")
    result = evaluate(df_train, df_test, args.kelly_fraction, args.model)

    print_report(result)


if __name__ == "__main__":
    main()
