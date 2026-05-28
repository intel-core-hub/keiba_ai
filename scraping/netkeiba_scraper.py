# scraping/netkeiba_scraper.py

import io
import re
import time
import random
import logging
import requests
import pandas as pd

from bs4 import BeautifulSoup
from datetime import datetime

from core.horse_history_builder import HorseHistoryBuilder

logger = logging.getLogger(__name__)


# =====================================================
# 定数
# =====================================================

# netkeiba db は EUC-JP
_ENCODING = "euc-jp"

# レース結果テーブルの目印となる列名（日本語）
# 複数テーブルがある場合に正しいものを特定するために使う
_RESULT_TABLE_MARKER = "馬名"

# リトライ設定
_MAX_RETRIES = 3
_RETRY_WAIT_BASE = 5.0   # 秒（指数バックオフ）


class ScraperError(Exception):
    """スクレイパー起因の回復不能エラー"""


class NetkeibaScraper:
    """
    Netkeiba Scraper

    目的:
    - 実データ接続
    - historical収集
    - live race取得
    - market data取得

    最重要:
    「壊れにくく」
    """

    BASE_URL = "https://db.netkeiba.com"

    def __init__(
        self,
        sleep_min: float = 1.5,
        sleep_max: float = 3.5,
    ) -> None:
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        })

    # =================================================
    # Safe Sleep
    # =================================================

    def _wait(self) -> None:
        time.sleep(random.uniform(self.sleep_min, self.sleep_max))

    # =================================================
    # Request（リトライ付き）
    # =================================================

    def fetch(self, url: str) -> str | None:
        """
        GETリクエスト。
        タイムアウト・5xx は指数バックオフでリトライ。
        404 など4xx はリトライしない。
        失敗時は None を返す（例外は握り潰さない → logger.warning で記録）。
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                self._wait()
                response = self.session.get(url, timeout=(3.05, 10.0))

                # 4xx はリトライしても無駄
                if 400 <= response.status_code < 500:
                    logger.warning(
                        "Client error %s for %s", response.status_code, url
                    )
                    return None

                response.raise_for_status()

                # --- 文字コードを EUC-JP に強制 ---
                # requests はデフォルトで Content-Type から推定するが、
                # netkeiba は charset を省略することがあり ISO-8859-1 と誤判定する。
                response.encoding = _ENCODING
                return response.text

            except requests.exceptions.Timeout:
                logger.warning("Timeout (attempt %d/%d): %s", attempt, _MAX_RETRIES, url)
            except requests.exceptions.HTTPError as e:
                logger.warning("HTTP error (attempt %d/%d): %s %s", attempt, _MAX_RETRIES, url, e)
            except requests.exceptions.RequestException as e:
                logger.warning("Request error (attempt %d/%d): %s %s", attempt, _MAX_RETRIES, url, e)

            if attempt < _MAX_RETRIES:
                wait = _RETRY_WAIT_BASE * (2 ** (attempt - 1))
                logger.info("Retry wait %.1fs", wait)
                time.sleep(wait)

        logger.error("All %d attempts failed: %s", _MAX_RETRIES, url)
        return None

    # =================================================
    # Race IDs From Date
    # =================================================

    def race_ids_by_date(self, date_str: str) -> list[str]:
        """
        指定日のレースID一覧を返す。

        Args:
            date_str: YYYYMMDD 形式

        Returns:
            race_id のリスト（重複なし・昇順）
        """
        url = f"{self.BASE_URL}/race/list/{date_str}/"
        html = self.fetch(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")

        race_ids = []
        for a in soup.find_all("a", href=True):
            match = re.search(r"/race/(\d{12})/", a["href"])
            if match:
                race_ids.append(match.group(1))

        return sorted(set(race_ids))

    # =================================================
    # Parse Race Page
    # =================================================

    def scrape_race(self, race_id: str) -> pd.DataFrame | None:
        """
        レース結果ページをスクレイプして DataFrame を返す。

        Returns:
            結果DataFrame、または取得・解析失敗時は None
        """
        url = f"{self.BASE_URL}/race/{race_id}/"
        html = self.fetch(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # --- タイトル取得 ---
        title_tag = soup.find("title")
        race_title = title_tag.text.strip() if title_tag else "UNKNOWN"

        # --- テーブル取得 ---
        # pandas 2.x 以降は文字列を直接渡せない → StringIO でラップ必須
        try:
            tables = pd.read_html(io.StringIO(html))
        except Exception as e:
            logger.warning("Could not parse tables in race %s: %s", race_id, e)
            return None

        # 複数テーブルの中からレース結果テーブルを特定
        # 「馬名」列を含むものを使う
        result_df = None
        for df in tables:
            if _RESULT_TABLE_MARKER in df.columns:
                result_df = df
                break

        if result_df is None:
            # フォールバック: 最初のテーブルを試す
            logger.warning(
                "Could not find result table by marker '%s' in race %s, "
                "falling back to tables[0]",
                _RESULT_TABLE_MARKER,
                race_id,
            )
            result_df = tables[0]

        # --- メタ情報付加 ---
        result_df = result_df.copy()
        horse_ids = []
        for a in soup.find_all("a", href=True):
            match = re.search(r"/horse/(\d{10,12})/", a["href"])
            if match:
                horse_ids.append(match.group(1))

        if horse_ids:
            padded = horse_ids[: len(result_df)]
            if len(padded) < len(result_df):
                padded.extend([None] * (len(result_df) - len(padded)))
            result_df["horse_id"] = padded

        result_df["race_id"] = race_id
        result_df["race_title"] = race_title
        result_df["scraped_at"] = datetime.utcnow().isoformat()

        return result_df

    def scrape_race_with_history(self, race_id: str) -> pd.DataFrame | None:
        race_df = self.scrape_race(race_id)
        if race_df is None or race_df.empty:
            return race_df

        race_df = self.minimal_features(race_df)
        history_builder = HorseHistoryBuilder(scraper=self)
        return history_builder.attach_horse_history(race_df)

    # =================================================
    # Historical Range
    # =================================================

    def scrape_date_range(
        self,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame | None:
        """
        日付範囲のレースをスクレイプして1つの DataFrame に結合して返す。

        Args:
            start_date: YYYYMMDD
            end_date:   YYYYMMDD
        """
        dates = pd.date_range(start=start_date, end=end_date)
        all_frames: list[pd.DataFrame] = []

        for d in dates:
            date_str = d.strftime("%Y%m%d")
            logger.info("[DATE] %s", date_str)

            race_ids = self.race_ids_by_date(date_str)
            logger.info("  races found: %d", len(race_ids))

            for race_id in race_ids:
                logger.info("  scraping %s", race_id)
                try:
                    df = self.scrape_race(race_id)
                    if df is not None:
                        all_frames.append(df)
                except Exception as e:
                    # 1レース失敗でも継続する。ただし必ずログに残す。
                    logger.error("Unexpected error for race %s: %s", race_id, e, exc_info=True)

        if not all_frames:
            logger.warning("No data collected for %s – %s", start_date, end_date)
            return None

        return pd.concat(all_frames, ignore_index=True)

    # =================================================
    # Save
    # =================================================

    def save_csv(self, df: pd.DataFrame, path: str) -> None:
        df.to_csv(path, index=False, encoding="utf-8-sig")
        logger.info("[SAVED] %s  rows=%d", path, len(df))

    # =================================================
    # Minimal Feature Builder
    # =================================================

    def minimal_features(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        """
        scraper段階の最低限の正規化のみ行う。
        feature engineering は dataset 側で実施する。

        実際のnetkeiba列名はスペース入り（例: "着 順", "人 気"）のため、
        マッピングは strip() 済みの名前で照合する。
        """
        df = raw_df.copy()

        # --- 列名のスペースを除去してから英語名にマッピング ---
        # netkeiba のHTMLテーブルは列名にスペースが混入することがある
        # 例: "着 順" "枠 番" "人 気"
        df.columns = [c.replace(" ", "") for c in df.columns]

        mapping = {
            "馬名":   "horse_name",
            "単勝":   "odds",
            "人気":   "favorite_rank",
            "着順":   "finishing_position",
            "枠番":   "frame_number",
            "馬番":   "horse_number",
            "性齢":   "sex_age_raw",
            "斤量":   "weight_carried",
            "騎手":   "jockey",
            "タイム":  "race_time",
            "着差":   "margin_raw",
            "調教師":  "trainer",
            "馬体重":  "horse_weight_raw",
        }
        df = df.rename(columns={c: v for c, v in mapping.items() if c in df.columns})

        # --- race_id を文字列として保持（12桁の数字は int64 に丸められる） ---
        if "race_id" in df.columns:
            df["race_id"] = df["race_id"].astype(str)

        # --- 数値変換 ---
        for col in ["odds", "finishing_position", "favorite_rank",
                    "weight_carried", "frame_number", "horse_number"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # --- 性齢を性別・年齢に分解 ---
        # 形式: "牝6" "牡4" "セ5" など
        if "sex_age_raw" in df.columns:
            df["sex"] = df["sex_age_raw"].str[0]         # 先頭1文字: 牝/牡/セ
            df["age"] = pd.to_numeric(
                df["sex_age_raw"].str[1:], errors="coerce"
            )
            df = df.drop(columns=["sex_age_raw"])

        # --- 馬体重を体重と増減に分解 ---
        # 形式: "480(-2)" "460(+4)" "492(0)"
        if "horse_weight_raw" in df.columns:
            extracted = df["horse_weight_raw"].astype(str).str.extract(
                r"(\d+)\(([+-]?\d+)\)"
            )
            df["horse_weight"] = pd.to_numeric(extracted[0], errors="coerce")
            df["horse_weight_diff"] = pd.to_numeric(extracted[1], errors="coerce")
            df = df.drop(columns=["horse_weight_raw"])

        # --- ターゲット生成 ---
        if "finishing_position" in df.columns:
            df["target_win"] = (df["finishing_position"] == 1).astype(int)
            df["target_place"] = (df["finishing_position"] <= 3).astype(int)

        return df

    def horse_history(self, horse_id: str) -> pd.DataFrame | None:
        history_builder = HorseHistoryBuilder(scraper=self)
        return history_builder.scrape_horse(horse_id)

    # =================================================
    # Live Race Odds
    # =================================================

    def live_odds(self, race_id: str) -> dict | None:
        """
        将来: リアルタイム接続用。
        現状は結果ページから単勝オッズを返す。
        """
        df = self.scrape_race(race_id)
        if df is None:
            return None

        result: dict = {}
        if "馬名" in df.columns and "単勝" in df.columns:
            for _, row in df.iterrows():
                horse = row.get("馬名")
                odds = row.get("単勝")
                if pd.notna(horse) and pd.notna(odds):
                    result[horse] = odds

        return result if result else None


# =====================================================
# ロギング設定ヘルパー
# =====================================================

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":
    _setup_logging()

    scraper = NetkeibaScraper(sleep_min=1.5, sleep_max=3.5)

    # --------------------------------------------------
    # Step1: 1レース取得して構造を確認する
    # --------------------------------------------------
    race_id = "202405020811"

    logger.info("=== scrape_race: %s ===", race_id)
    df = scraper.scrape_race(race_id)

    if df is not None:
        logger.info("raw columns: %s", list(df.columns))
        logger.info("rows: %d", len(df))
        print(df.head())

        clean = scraper.minimal_features(df)
        logger.info("clean columns: %s", list(clean.columns))
        print(clean.head())

        import os
        os.makedirs("data/raw", exist_ok=True)
        scraper.save_csv(clean, "data/raw/sample_race.csv")
    else:
        logger.error("scrape_race returned None — ネットワーク or HTMLの問題")

    # --------------------------------------------------
    # Step2: 日付一覧取得（コメントアウト — 確認後に解除）
    # --------------------------------------------------
    # logger.info("=== race_ids_by_date ===")
    # ids = scraper.race_ids_by_date("20240502")
    # logger.info("found: %s", ids)

    # --------------------------------------------------
    # Step3: 週単位の収集（Step2確認後に解除）
    # --------------------------------------------------
    # historical = scraper.scrape_date_range("20240501", "20240507")
    # if historical is not None:
    #     scraper.save_csv(historical, "data/raw/historical_week.csv")
