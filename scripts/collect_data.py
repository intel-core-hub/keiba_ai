# scripts/collect_data.py
#
# 使い方:
#   1日分:      python scripts/collect_data.py 20240505
#   範囲指定:   python scripts/collect_data.py 20240601 20240630
#   JRAのみ:    python scripts/collect_data.py 20240601 20240630 --jra-only
#   件数制限:   python scripts/collect_data.py 20240601 20240630 --jra-only --limit 3
#   出力先変更: python scripts/collect_data.py 20240601 20240630 --out data/raw/jun.csv

import argparse
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraping.netkeiba_scraper import NetkeibaScraper
from core.horse_history_builder import HorseHistoryBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# =====================================================
# JRA 場コード（01〜10 = 札幌〜小倉）
# =====================================================
_JRA_VENUE_CODES = {"01", "02", "03", "04", "05", "06", "07", "08", "09", "10"}

_JRA_VENUE_NAMES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉",
}


def is_jra(race_id: str) -> bool:
    """
    race_id の場コード（5〜6桁目）が JRA の場合 True を返す。

    race_id 形式: YYYY + 場コード(2桁) + 回(2桁) + 日(2桁) + R(2桁)
    例: 202405020811 → 場コード=05（東京）→ JRA
        202430050201 → 場コード=30（地方）→ 非JRA
    """
    s = str(race_id)
    if len(s) < 6:
        return False
    return s[4:6] in _JRA_VENUE_CODES


# =====================================================
# 引数パース
# =====================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="netkeiba からレース結果と馬過去成績を収集する"
    )
    parser.add_argument(
        "start_date",
        help="収集開始日（YYYYMMDD）",
    )
    parser.add_argument(
        "end_date",
        nargs="?",
        default=None,
        help="収集終了日（YYYYMMDD）。省略時は start_date の1日分のみ。",
    )
    parser.add_argument(
        "--jra-only",
        action="store_true",
        default=False,
        dest="jra_only",
        help="JRA レース（場コード01〜10）のみ収集する。地方競馬をスキップ。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="収集するレース数の上限（デバッグ用）",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="出力CSVパス。省略時は data/raw/phase4_{start}_{end}.csv",
    )
    parser.add_argument(
        "--sleep-min",
        type=float,
        default=1.5,
        dest="sleep_min",
    )
    parser.add_argument(
        "--sleep-max",
        type=float,
        default=3.5,
        dest="sleep_max",
    )
    return parser.parse_args()


# =====================================================
# 収集メイン
# =====================================================

def collect(args: argparse.Namespace) -> None:
    start = args.start_date
    end   = args.end_date if args.end_date else args.start_date

    # 出力パスの決定
    out_path = args.out
    if out_path is None:
        os.makedirs("data/raw", exist_ok=True)
        suffix = "_jra" if args.jra_only else ""
        if start == end:
            out_path = f"data/raw/phase4{suffix}_{start}.csv"
        else:
            out_path = f"data/raw/phase4{suffix}_{start}_{end}.csv"

    logger.info("収集期間: %s → %s", start, end)
    logger.info("モード:   %s", "JRAのみ" if args.jra_only else "全競馬場")
    logger.info("出力先:   %s", out_path)
    if args.limit:
        logger.info("レース上限: %d", args.limit)

    scraper = NetkeibaScraper(
        sleep_min=args.sleep_min,
        sleep_max=args.sleep_max,
    )
    builder = HorseHistoryBuilder(scraper=scraper)

    dates = pd.date_range(start=start, end=end)
    all_frames = []
    race_count = 0
    skipped_count = 0

    for d in dates:
        date_str = d.strftime("%Y%m%d")
        race_ids = scraper.race_ids_by_date(date_str)

        if not race_ids:
            continue

        # JRAのみモード: 地方競馬の race_id をスキップ
        if args.jra_only:
            jra_ids    = [r for r in race_ids if is_jra(r)]
            skipped    = len(race_ids) - len(jra_ids)
            skipped_count += skipped
            race_ids   = jra_ids

            if not race_ids:
                continue

            venue_names = {
                _JRA_VENUE_NAMES.get(r[4:6], r[4:6])
                for r in race_ids
            }
            logger.info(
                "[%s] JRA %d レース（%s）| 地方スキップ: %d",
                date_str, len(race_ids),
                "・".join(sorted(venue_names)),
                skipped,
            )
        else:
            logger.info("[%s] %d レース", date_str, len(race_ids))

        for race_id in race_ids:
            if args.limit and race_count >= args.limit:
                logger.info("レース上限 %d に達したので終了", args.limit)
                break

            logger.info("  scraping %s", race_id)
            try:
                raw = scraper.scrape_race(race_id)
                if raw is None:
                    continue

                clean = scraper.minimal_features(raw)
                clean = builder.attach_horse_history(clean)
                all_frames.append(clean)
                race_count += 1

            except Exception as e:
                logger.error(
                    "  race %s でエラー: %s", race_id, e, exc_info=True
                )

        if args.limit and race_count >= args.limit:
            break

    if not all_frames:
        logger.warning("データが1件も収集できませんでした")
        return

    df = pd.concat(all_frames, ignore_index=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    logger.info("=" * 50)
    logger.info("収集完了")
    logger.info("  レース数:  %d", race_count)
    logger.info("  馬（行）数: %d", len(df))
    logger.info("  保存先:    %s", out_path)
    if args.jra_only and skipped_count > 0:
        logger.info("  地方スキップ: %d レース", skipped_count)

    if "avg_finish_last5" in df.columns:
        nonzero = (df["avg_finish_last5"] != 0.0).sum()
        logger.info(
            "  avg_finish_last5 非ゼロ: %d/%d頭", nonzero, len(df)
        )
    if "avg_speed_index_last5" in df.columns:
        nonzero_spd = (df["avg_speed_index_last5"] != 0.0).sum()
        logger.info(
            "  avg_speed_index_last5 非ゼロ: %d/%d頭", nonzero_spd, len(df)
        )
    logger.info("=" * 50)


if __name__ == "__main__":
    collect(parse_args())
