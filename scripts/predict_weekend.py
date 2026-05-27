# scripts/predict_weekend.py
#
# 指定日のJRAレースに対して勝利確率・期待値を計算し、
# 「買い推奨馬」を出力する週次予測スクリプト。
#
# 使い方:
#   python scripts/predict_weekend.py --date 20240601
#   python scripts/predict_weekend.py --date 20240601 --ev-threshold 1.1
#   python scripts/predict_weekend.py --date 20240601 --out results/20240601.csv
#   python scripts/predict_weekend.py --date 20240601 --all    # 全馬を出力

import argparse
import logging
import os
import sys
from datetime import datetime

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraping.netkeiba_scraper import NetkeibaScraper
from core.horse_history_builder import HorseHistoryBuilder
from learning.uncertainty import estimate_uncertainty

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# =====================================================
# 設定
# =====================================================

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

_JRA_VENUE_CODES = {"01","02","03","04","05","06","07","08","09","10"}
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
        description="指定日のJRAレース予測と買い推奨馬の出力"
    )
    parser.add_argument(
        "--date",
        required=True,
        help="予測対象日（YYYYMMDD）",
    )
    parser.add_argument(
        "--model",
        default=MODEL_PATH,
        help="モデルパス（デフォルト: models/prediction_model.pkl）",
    )
    parser.add_argument(
        "--ev-threshold",
        type=float,
        default=1.0,
        dest="ev_threshold",
        help="買い推奨の期待値閾値（デフォルト: 1.0）",
    )
    parser.add_argument(
        "--min-calibration-gap",
        type=float,
        default=MIN_CALIBRATION_GAP_DEFAULT,
        dest="min_calibration_gap",
        help="この calibration_gap を超える馬のみ推奨対象にする（デフォルト: 0.12）",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="結果CSVの出力先。省略時はコンソールのみ。",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="推奨馬だけでなく全馬を出力する",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=2,
        dest="top_n",
        help="各レースで推奨表示する最大頭数（デフォルト: 2）",
    )
    parser.add_argument(
        "--max-uncertainty",
        type=float,
        default=None,
        dest="max_uncertainty",
        help="この不確実性を超える馬は推奨から除外する（省略時はモデル既定値）",
    )
    parser.add_argument(
        "--sleep-min", type=float, default=1.5, dest="sleep_min",
    )
    parser.add_argument(
        "--sleep-max", type=float, default=3.5, dest="sleep_max",
    )
    return parser.parse_args()


# =====================================================
# モデルロード
# =====================================================

def load_model(path: str) -> tuple:
    """
    prediction_model.pkl を読み込む。
    monthly_retrain.py が保存した形式（dict）と
    旧形式（Pipeline 直接）の両方に対応。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"モデルが見つかりません: {path}\n"
            "先に python scripts/monthly_retrain.py を実行してください。"
        )

    payload = joblib.load(path)

    if isinstance(payload, dict):
        model         = payload["model"]
        features      = payload.get("features", FEATURE_COLS)
        trained_month = payload.get("trained_month", "不明")
        metrics       = payload.get("metrics", {})
        uncertainty_profile = payload.get("uncertainty_profile", metrics.get("uncertainty_profile", {}))
    else:
        # 旧形式（Pipeline 直接保存）
        model         = payload
        features      = FEATURE_COLS
        trained_month = "不明"
        metrics       = {}
        uncertainty_profile = {}

    logger.info(
        "モデル読み込み完了: 学習月=%s, Brier=%.4f",
        trained_month,
        metrics.get("brier", float("nan")),
    )
    return model, features, uncertainty_profile


# =====================================================
# 予測
# =====================================================

def predict_race(
    model,
    features: list[str],
    race_df: pd.DataFrame,
    uncertainty_profile: dict | None = None,
    ev_threshold: float = 1.0,
    top_n: int = 2,
    max_uncertainty: float | None = None,
    min_calibration_gap: float = MIN_CALIBRATION_GAP_DEFAULT,
) -> pd.DataFrame:
    """
    1レース分の DataFrame に予測確率・期待値を付加して返す。
    """
    df = race_df.copy()

    # 不足している特徴量列を 0 で補完
    for col in features:
        if col not in df.columns:
            df[col] = 0.0

    X = df[features].copy()

    # 数値変換
    for col in features:
        X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0.0)

    try:
        proba = model.predict_proba(X.values)[:, 1]
    except Exception as e:
        logger.error("predict_proba 失敗: %s", e)
        proba = np.full(len(df), 1.0 / len(df))

    df["pred_prob"] = np.round(proba, 4)

    uncertainty_rows = [
        estimate_uncertainty(float(p), uncertainty_profile)
        for p in proba
    ]
    uncertainty_df = pd.DataFrame(uncertainty_rows)
    df = pd.concat([df.reset_index(drop=True), uncertainty_df.reset_index(drop=True)], axis=1)

    if max_uncertainty is None:
        max_uncertainty = float((uncertainty_profile or {}).get("recommended_max_uncertainty", 0.65))

    df["bet_eligible"] = df["uncertainty_score"] <= max_uncertainty

    odds_source = df["odds"] if "odds" in df.columns else pd.Series(np.nan, index=df.index)
    odds_num = pd.to_numeric(odds_source, errors="coerce")
    implied_prob = np.where(odds_num > 0, 1.0 / odds_num, np.nan)
    df["implied_prob"] = np.round(implied_prob, 4)
    df["calibration_gap"] = np.where(
        odds_num > 0,
        np.round(np.abs(df["pred_prob"] - df["implied_prob"]), 4),
        np.nan,
    )

    # 期待値 = 予測確率 × 単勝オッズ
    df["expected_value"] = np.where(
        odds_num.notna(),
        np.round(df["pred_prob"] * odds_num, 3),
        np.nan,
    )

    # 推奨フラグ: レース内で EV 閾値と calibration_gap 閾値を満たす上位 top_n 頭
    df["recommend"] = False
    if "race_id" in df.columns:
        for _, group in df.groupby("race_id"):
            candidates = group[
                (group["expected_value"] >= ev_threshold)
                & (group["bet_eligible"])
                & (group["calibration_gap"] > min_calibration_gap)
            ]
            if candidates.empty:
                continue
            selected = candidates.sort_values("expected_value", ascending=False).head(top_n)
            df.loc[selected.index, "recommend"] = True
    else:
        candidates = df[
            (df["expected_value"] >= ev_threshold)
            & (df["bet_eligible"])
            & (df["calibration_gap"] > min_calibration_gap)
        ]
        if not candidates.empty:
            selected = candidates.sort_values("expected_value", ascending=False).head(top_n)
            df.loc[selected.index, "recommend"] = True

    # レース内順位（確率降順）
    df["prob_rank"] = df["pred_prob"].rank(ascending=False, method="min").astype(int)

    return df


# =====================================================
# 表示・出力
# =====================================================

def print_race_result(
    race_df: pd.DataFrame,
    ev_threshold: float,
    min_calibration_gap: float,
    show_all: bool,
    max_uncertainty: float | None,
) -> None:
    """1レース分の予測結果をコンソールに表示する。"""
    race_id    = race_df["race_id"].iloc[0] if "race_id" in race_df.columns else "?"
    race_title = race_df["race_title"].iloc[0] if "race_title" in race_df.columns else ""
    venue_code = str(race_id)[4:6]
    venue_name = _JRA_VENUE_NAMES.get(venue_code, "")

    # レース番号
    race_no = str(race_id)[10:12] if len(str(race_id)) >= 12 else "?"
    print(f"\n【R{race_no} {venue_name} {race_title}】")
    print(f"  race_id: {race_id}")
    print()

    display_cols = ["prob_rank", "horse_name", "odds", "pred_prob", "calibration_gap",
                    "expected_value", "uncertainty_score", "prediction_interval_low",
                    "prediction_interval_high", "recommend", "avg_finish_last5",
                    "rest_days"]
    display_cols = [c for c in display_cols if c in race_df.columns]

    # 確率降順にソート
    df_sorted = race_df.sort_values("pred_prob", ascending=False)

    # 全馬表示 or 推奨馬のみ（EV上位 top_n 頭）
    if show_all:
        display_df = df_sorted
    else:
        display_df = df_sorted[df_sorted["recommend"] == True]

    if display_df.empty:
        print(
            "  （EV > {:.1f} かつ gap > {:.2f} の馬はありません）".format(
                ev_threshold,
                min_calibration_gap,
            )
        )
        return

    # ヘッダー
    print(f"  {'順':>3} {'馬名':<14} {'オッズ':>6} {'予測確率':>8} {'gap':>6} "
        f"{'期待値':>7} {'不確実':>7} {'推奨':>4} {'avg着順':>7} {'休養日':>6}")
    print(f"  {'-'*3} {'-'*14} {'-'*6} {'-'*8} {'-'*6} {'-'*7} {'-'*7} {'-'*4} {'-'*7} {'-'*6}")

    for _, row in display_df.iterrows():
        recommend_mark = "✅ 買い" if row.get("recommend") else "      "
        avg_fin = f"{row.get('avg_finish_last5', 0):.1f}" if row.get("avg_finish_last5") else "  -"
        rest    = f"{int(row.get('rest_days', 0))}"        if row.get("rest_days")        else "  -"
        print(
            f"  {row.get('prob_rank', '-'):>3} "
            f"{str(row.get('horse_name', '')):<14} "
            f"{row.get('odds', '-'):>6} "
            f"{row.get('pred_prob', 0):>8.4f} "
            f"{row.get('calibration_gap', 0):>6.4f} "
            f"{row.get('expected_value', 0):>7.3f} "
            f"{row.get('uncertainty_score', 0):>7.3f} "
            f"{recommend_mark:>6} "
            f"{avg_fin:>7} "
            f"{rest:>6}"
        )


# =====================================================
# メイン
# =====================================================

def main() -> None:
    args = parse_args()

    # モデルロード
    model, features, uncertainty_profile = load_model(args.model)

    # スクレイパー初期化
    scraper = NetkeibaScraper(
        sleep_min=args.sleep_min,
        sleep_max=args.sleep_max,
    )
    builder = HorseHistoryBuilder(scraper=scraper)

    # 対象日のレースID取得
    logger.info("対象日: %s", args.date)
    race_ids = scraper.race_ids_by_date(args.date)

    # JRAのみに絞る
    jra_ids = [r for r in race_ids if r[4:6] in _JRA_VENUE_CODES]
    skipped = len(race_ids) - len(jra_ids)
    logger.info(
        "レース: JRA=%d件 / スキップ(地方)=%d件",
        len(jra_ids), skipped,
    )

    if not jra_ids:
        logger.warning("この日のJRAレースが見つかりませんでした。")
        return

    # 結果収集
    all_results = []
    buy_count   = 0

    print()
    print("=" * 60)
    print(f"  {args.date[:4]}年{int(args.date[4:6])}月{int(args.date[6:8])}日  JRA予測レポート")
    print(f"  期待値閾値: {args.ev_threshold}")
    print(f"  calibration_gap閾値: > {args.min_calibration_gap}")
    print("=" * 60)

    for race_id in jra_ids:
        logger.info("予測中: %s", race_id)
        try:
            raw   = scraper.scrape_race(race_id)
            if raw is None:
                continue

            clean = scraper.minimal_features(raw)
            clean = builder.attach_horse_history(clean)
            pred  = predict_race(
                model,
                features,
                clean,
                uncertainty_profile=uncertainty_profile,
                ev_threshold=args.ev_threshold,
                top_n=args.top_n,
                max_uncertainty=args.max_uncertainty,
                min_calibration_gap=args.min_calibration_gap,
            )

            print_race_result(
                pred,
                args.ev_threshold,
                args.min_calibration_gap,
                args.all,
                args.max_uncertainty,
            )

            buy_count += int(pred["recommend"].sum())
            all_results.append(pred)

        except Exception as e:
            logger.error("race %s でエラー: %s", race_id, e, exc_info=True)

    # サマリ
    print()
    print("=" * 60)
    print(f"  【本日の推奨馬数】 {buy_count} 頭 "
            f"（EV > {args.ev_threshold}、gap > {args.min_calibration_gap}、各レース上位{args.top_n}頭）")

    if all_results:
        df_all = pd.concat(all_results, ignore_index=True)
        buy_df = df_all[df_all["recommend"]].copy()
        if not buy_df.empty:
            avg_ev = buy_df["expected_value"].mean()
            print(f"  推奨馬の平均期待値: {avg_ev:.3f}")
            print()
            print("  ─── 推奨馬一覧 ─────────────────────────────────")
            print(f"  {'レース':>4} {'場':>4} {'馬名':<14} {'オッズ':>6} "
                  f"{'確率':>7} {'期待値':>7}")
            print(f"  {'─'*4} {'─'*4} {'─'*14} {'─'*6} {'─'*7} {'─'*7}")
            for _, row in buy_df.sort_values(
                "expected_value", ascending=False
            ).iterrows():
                race_id = str(row.get("race_id",""))
                race_no = race_id[10:12] if len(race_id) >= 12 else "?"
                venue   = _JRA_VENUE_NAMES.get(race_id[4:6], "??")
                print(
                    f"  R{race_no:>2} {venue:>4} "
                    f"{str(row.get('horse_name','')):<14} "
                    f"{row.get('odds',0):>6.1f} "
                    f"{row.get('pred_prob',0):>7.4f} "
                    f"{row.get('expected_value',0):>7.3f}"
                )
    print("=" * 60)

    # CSV出力
    if args.out and all_results:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        df_all = pd.concat(all_results, ignore_index=True)
        df_out = df_all if args.all else df_all[df_all["recommend"]]
        df_out.to_csv(args.out, index=False, encoding="utf-8-sig")
        logger.info("結果保存: %s (%d行)", args.out, len(df_out))


if __name__ == "__main__":
    main()
