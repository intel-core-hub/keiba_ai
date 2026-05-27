# scripts/backtest_result.py
#
# 収集済みCSV（finishing_position 付き）に対して予測を再計算し、
# 実際の結果と照合して回収率・的中率を出力する。
#
# 使い方:
#   python scripts/backtest_result.py --csv data/raw/phase4_jra_20240601.csv
#   python scripts/backtest_result.py --csv data/raw/phase4_jra_20240601.csv --top-n 1 --ev-threshold 1.3
#   python scripts/backtest_result.py --csv data/raw/phase4_jra_20240601.csv --out results/backtest_20240601.csv

import argparse
import logging
import os
import sys

import joblib
import numpy as np
import pandas as pd
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MODEL_PATH   = "models/prediction_model.pkl"
MIN_CALIBRATION_GAP_DEFAULT = 0.12
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

_JRA_VENUE_NAMES = {
    "01":"札幌","02":"函館","03":"福島","04":"新潟",
    "05":"東京","06":"中山","07":"中京","08":"京都",
    "09":"阪神","10":"小倉",
}


# =====================================================
# 引数パース
# =====================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="収集済みCSVで予測を再計算し実結果と照合する"
    )
    parser.add_argument("--csv",  required=True, help="phase4_jra_*.csv のパス")
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument(
        "--strategy",
        choices=("ev", "prob"),
        default="ev",
        help="レース内の選択基準（ev=期待値順, prob=確率順）",
    )
    parser.add_argument("--top-n", type=int, default=1, dest="top_n",
                        help="各レースで推奨する最大頭数（デフォルト: 1）")
    parser.add_argument("--ev-threshold", type=float, default=1.0, dest="ev_threshold",
                        help="買い推奨の期待値閾値（デフォルト: 1.0）")
    parser.add_argument("--min-calibration-gap", type=float, default=MIN_CALIBRATION_GAP_DEFAULT,
                        dest="min_calibration_gap",
                        help="この calibration_gap を超える馬のみ推奨対象にする（デフォルト: 0.12）")
    parser.add_argument("--odds-max", type=float, default=None, dest="odds_max",
                        help="このオッズ以下の馬だけを推奨対象にする")
    parser.add_argument("--out", default=None, help="結果CSV の出力先")
    parser.add_argument(
        "--jra-only",
        action="store_true",
        default=True,
        dest="jra_only",
        help="JRAレースのみ対象（デフォルト: True）",
    )
    return parser.parse_args()


# =====================================================
# モデルロード
# =====================================================

def load_model(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"モデルが見つかりません: {path}\n"
            "先に python scripts/monthly_retrain.py を実行してください。"
        )
    # scikit-learn のバージョン不整合による unpickle 時の警告を抑制する。
    # 利用している sklearn のバージョンによっては InconsistentVersionWarning の定義場所が異なるため
    # 複数候補からインポートを試み、あればフィルタリングする。
    try:
        from sklearn.exceptions import InconsistentVersionWarning  # type: ignore
    except Exception:
        try:
            from sklearn.base import InconsistentVersionWarning  # type: ignore
        except Exception:
            InconsistentVersionWarning = None  # type: ignore

    if InconsistentVersionWarning is not None:
        warnings.filterwarnings("ignore", category=InconsistentVersionWarning)

    payload = joblib.load(path)
    if isinstance(payload, dict):
        model    = payload["model"]
        features = payload.get("features", FEATURE_COLS)
        logger.info("モデル: 学習月=%s, Brier=%.4f",
                    payload.get("trained_month","?"),
                    payload.get("metrics",{}).get("brier", float("nan")))
    else:
        model    = payload
        features = FEATURE_COLS
    return model, features


# =====================================================
# 予測
# =====================================================

def predict_df(model, features: list, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in features:
        if col not in df.columns:
            df[col] = 0.0

    X = df[features].copy()
    for col in features:
        X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0.0)

    try:
        proba = model.predict_proba(X.values)[:, 1]
    except Exception as e:
        logger.error("predict_proba 失敗: %s", e)
        n = len(df)
        proba = np.full(n, 1.0 / n)

    df["pred_prob"]      = np.round(proba, 4)
    odds_num             = pd.to_numeric(df["odds"], errors="coerce")
    implied_prob         = np.where(odds_num > 0, 1.0 / odds_num, np.nan)
    df["implied_prob"]   = np.round(implied_prob, 4)
    df["calibration_gap"] = np.where(
        odds_num > 0,
        np.round(np.abs(df["pred_prob"] - df["implied_prob"]), 4),
        np.nan,
    )
    df["expected_value"] = np.round(df["pred_prob"] * odds_num, 3)
    return df


# =====================================================
# レースごとの照合
# =====================================================

def evaluate_races(
    df: pd.DataFrame,
    strategy: str,
    top_n: int,
    ev_threshold: float,
    odds_max: float | None,
    min_calibration_gap: float,
) -> tuple[list[dict], list[dict]]:
    """
    レースごとに推奨馬を選び、実際の結果と照合する。

    Returns:
        race_records: レース単位のサマリリスト
        horse_records: 推奨馬ごとの詳細リスト
    """
    race_records  = []
    horse_records = []

    def _safe_int(value, default: int | None = None) -> int | None:
        numeric = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric):
            return default
        return int(numeric)

    for race_id, group in df.groupby("race_id"):
        group = group.copy()

        # detect finishing position column name in various backtest CSVs
        pos_col_candidates = [
            "finishing_position",
            "actual_pos",
            "position",
            "fin_pos",
        ]
        pos_col = None
        for c in pos_col_candidates:
            if c in group.columns:
                pos_col = c
                break
        if pos_col is None:
            # fallback: try 'actual_pos' as default if missing
            pos_col = "actual_pos"

        if odds_max is not None:
            odds_mask = pd.to_numeric(group["odds"], errors="coerce") <= odds_max
            group = group[odds_mask.fillna(False)].copy()

        group = group[group["calibration_gap"] > min_calibration_gap].copy()

        if group.empty:
            race_records.append({
                "race_id":    race_id,
                "race_title": "",
                "recommend":  False,
                "hit":        False,
                "pnl":        0.0,
            })
            continue

        if strategy == "prob":
            # 確率最大馬を優先する。EV閾値は使わず、予測確率の上位を採用する。
            score_col = "pred_prob"
        else:
            # 既存のEV最大戦略
            score_col = "expected_value"

        group = group.sort_values(score_col, ascending=False)
        if strategy == "prob":
            candidates = group.head(top_n)
        else:
            candidates = group[group[score_col] >= ev_threshold].head(top_n)

        if candidates.empty:
            race_records.append({
                "race_id":    race_id,
                "race_title": group["race_title"].iloc[0] if "race_title" in group.columns else "",
                "recommend":  False,
                "hit":        False,
                "pnl":        0.0,
            })
            continue

        # 実際の1着馬
        winner = group[pd.to_numeric(group[pos_col], errors="coerce") == 1]

        for _, row in candidates.iterrows():
            odds_val    = float(pd.to_numeric(row["odds"], errors="coerce") or 0)
            actual_pos  = _safe_int(row[pos_col])
            if actual_pos is None:
                continue
            is_hit      = (actual_pos == 1)
            pnl         = (odds_val - 1) if is_hit else -1.0  # 1単位ベット

            horse_records.append({
                "race_id":       race_id,
                "race_title":    row.get("race_title", ""),
                "horse_name":    row.get("horse_name", ""),
                "odds":          odds_val,
                "pred_prob":     row["pred_prob"],
                "calibration_gap": row.get("calibration_gap", np.nan),
                "expected_value":row["expected_value"],
                "actual_pos":    actual_pos,
                "hit":           is_hit,
                "pnl":           round(pnl, 2),
            })

        race_hit = any(
            _safe_int(r[pos_col]) == 1
            for _, r in candidates.iterrows()
            if _safe_int(r[pos_col]) is not None
        )
        race_pnl = sum(
            (float(pd.to_numeric(r["odds"], errors="coerce") or 0) - 1)
            if _safe_int(r[pos_col]) == 1
            else -1.0
            for _, r in candidates.iterrows()
            if _safe_int(r[pos_col]) is not None
        )

        race_records.append({
            "race_id":    race_id,
            "race_title": group["race_title"].iloc[0] if "race_title" in group.columns else "",
            "recommend":  True,
            "hit":        race_hit,
            "pnl":        round(race_pnl, 2),
        })

    return race_records, horse_records


# =====================================================
# レポート表示
# =====================================================

def print_report(
    horse_records: list[dict],
    race_records:  list[dict],
    strategy:      str,
    top_n:         int,
    ev_threshold:  float,
    odds_max:      float | None,
    min_calibration_gap: float,
) -> None:
    if not horse_records:
        print("推奨馬が0頭でした。--ev-threshold か --min-calibration-gap を見直してください。")
        return

    df_h = pd.DataFrame(horse_records)
    df_r = pd.DataFrame(race_records)

    total_bets    = len(df_h)
    total_hits    = int(df_h["hit"].sum())
    total_pnl     = float(df_h["pnl"].sum())
    hit_rate      = round(total_hits / total_bets * 100, 1) if total_bets > 0 else 0
    roi           = round((total_pnl / total_bets + 1) * 100, 1) if total_bets > 0 else 0
    avg_ev        = round(float(df_h["expected_value"].mean()), 3)
    avg_odds      = round(float(df_h["odds"].mean()), 1)
    recommend_races = int(df_r["recommend"].sum())
    total_races     = len(df_r)

    print()
    print("=" * 60)
    print("  バックテスト結果レポート")
    print("=" * 60)
    if strategy == "prob":
        print(f"  推奨条件: 確率順、各レース上位 {top_n} 頭")
    else:
        print(f"  推奨条件: EV > {ev_threshold}、各レース上位 {top_n} 頭")
    print(f"  対象レース: {total_races} レース（推奨あり: {recommend_races} レース）")
        print(f"  calibration_gap閾値: > {min_calibration_gap}")
    print()
    print("  【回収率・的中率】")
    print(f"    総ベット数:    {total_bets} 回")
    print(f"    的中数:        {total_hits} 回")
    print(f"    的中率:        {hit_rate}%")
    hit_marker = "✅" if roi >= 100 else "  "
    print(f"    ROI:           {roi}%  {hit_marker}")
    print(f"    累積収支:      {total_pnl:+.1f} 単位")
    print(f"    平均期待値:    {avg_ev}")
    print(f"    平均オッズ:    {avg_odds} 倍")
    if odds_max is not None:
        print(f"    オッズ上限:    {odds_max} 倍以下")
    print()

    # 推奨馬の詳細（的中馬を強調）
    print("  【推奨馬一覧】")
        print(f"  {'馬名':<14} {'オッズ':>6} {'確率':>7} {'gap':>6} {'EV':>6} "
            f"{'実着順':>5} {'結果':>6} {'収支':>6}")
        print(f"  {'─'*14} {'─'*6} {'─'*7} {'─'*6} {'─'*6} "
            f"{'─'*5} {'─'*6} {'─'*6}")

    df_sorted = df_h.sort_values("expected_value", ascending=False)
    for _, row in df_sorted.iterrows():
        result_mark = "🎯 的中" if row["hit"] else "      "
        print(
            f"  {str(row['horse_name']):<14} "
            f"{row['odds']:>6.1f} "
            f"{row['pred_prob']:>7.4f} "
            f"{row.get('calibration_gap', 0):>6.4f} "
            f"{row['expected_value']:>6.3f} "
            f"{int(row['actual_pos']):>5} "
            f"{result_mark:>6} "
            f"{row['pnl']:>+6.1f}"
        )
    print("=" * 60)


# =====================================================
# メイン
# =====================================================

def main() -> None:
    args = parse_args()

    # モデルロード
    model, features = load_model(args.model)

    # データ読み込み
    logger.info("CSV読み込み: %s", args.csv)
    df = pd.read_csv(args.csv, low_memory=False)
    logger.info("行数: %d, レース数: %d", len(df), df["race_id"].nunique())

    # JRAフィルタ（地方競馬を除外）
    if args.jra_only and "race_id" in df.columns:
        _JRA_CODES = {"01","02","03","04","05","06","07","08","09","10"}
        jra_mask = df["race_id"].astype(str).str[4:6].isin(_JRA_CODES)
        before = len(df)
        df = df[jra_mask].reset_index(drop=True)
        logger.info("JRAフィルタ後: %d → %d行", before, len(df))

    if len(df) == 0:
        logger.error("データが0行になりました。--jra-only を外してみてください。")
        return

    logger.info("対象レース数: %d", df["race_id"].nunique())

    # 予測
    df = predict_df(model, features, df)

    # 照合
    race_records, horse_records = evaluate_races(
        df,
        args.strategy,
        args.top_n,
        args.ev_threshold,
        args.odds_max,
        args.min_calibration_gap,
    )

    # レポート
    print_report(
        horse_records,
        race_records,
        args.strategy,
        args.top_n,
        args.ev_threshold,
        args.odds_max,
        args.min_calibration_gap,
    )

    # CSV出力
    if args.out and horse_records:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        pd.DataFrame(horse_records).to_csv(args.out, index=False, encoding="utf-8-sig")
        logger.info("結果保存: %s", args.out)


if __name__ == "__main__":
    main()
