from __future__ import annotations

import re
from datetime import date, datetime
from io import StringIO
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd


# =====================================================
# netkeiba /horse/result/{id}/ 列番号マッピング
#
# header=None で取得したとき、テーブルの列構成は固定:
#
#   列00: 日付      列09: オッズ   列10: 人気
#   列11: 着順      列14: 距離     列18: タイム
#   列27: 上り3F    列28: 馬体重
#
# ※ header=0（<th>認識）では "上り" が列23（空欄系）に
#    誤マッピングされることを実データで確認済み。
#    header=None + 固定列番号が唯一確実な方法。
#
# 実データ検証済み馬:
#   ソウキュウ (2021106800): 列27=[41.3,44.5,37.7,...]
#   カンバーランド (2021105709): 列27=[45.0,41.1,44.5,...]
# =====================================================

_DATE_COL   = 0    # 日付（"2024/04/28" 形式）
_FINISH_COL = 11   # 着順
_AGARI_COL  = 27   # 上り3F
_EXPECTED_COLS = 33

# 上り3F の物理的妥当範囲（秒）。範囲外は誤取得とみなし NaN。
_AGARI_MIN = 30.0
_AGARI_MAX = 50.0

# rest_days の妥当範囲。異常値は除外。
_REST_DAYS_MAX = 730  # 2年以上は異常値とみなす


# =====================================================
# 日付ユーティリティ
# =====================================================

def _parse_race_title_date(title: str | None) -> date | None:
    """
    race_title から対象レースの日付を取得する。
    例: "3歳未勝利｜2024年6月1日 | 競馬データベース" → date(2024, 6, 1)
    """
    if not isinstance(title, str):
        return None
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', title)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _parse_horse_page_date(d_str: str | None) -> date | None:
    """
    馬ページの日付列（列0）の文字列を date に変換する。
    例: "2024/04/28" → date(2024, 4, 28)
    """
    if not isinstance(d_str, str) or not d_str.strip():
        return None
    for fmt in ("%Y/%m/%d", "%Y年%m月%d日", "%Y-%m-%d"):
        try:
            return datetime.strptime(d_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


# =====================================================
# HorseHistoryBuilder
# =====================================================

@dataclass
class HorseHistoryBuilder:
    scraper: Any
    _history_cache: Dict[str, Optional[pd.DataFrame]] = field(
        default_factory=dict, repr=False
    )

    # =================================================
    # テーブル取得
    # =================================================

    def _parse_result_table(self, html: str) -> Optional[pd.DataFrame]:
        """
        header=None で取得し、列数=33 かつ 列11が着順パターンの
        テーブルを成績テーブルとして返す。
        """
        try:
            tables = pd.read_html(StringIO(html), header=None)
        except Exception:
            return None

        for t in tables:
            if len(t.columns) != _EXPECTED_COLS:
                continue
            col11 = [str(v) for v in t.iloc[:, _FINISH_COL].tolist()]
            if any(v.isdigit() or v in ("中", "除", "取", "失") for v in col11):
                return t.copy()

        return None

    # =================================================
    # 馬成績ページ取得
    # =================================================

    def scrape_horse(self, horse_id: str) -> Optional[pd.DataFrame]:
        if not horse_id:
            return None

        if horse_id in self._history_cache:
            cached = self._history_cache[horse_id]
            return None if cached is None else cached.copy()

        url = f"{self.scraper.BASE_URL}/horse/result/{horse_id}/"
        html = self.scraper.fetch(url)
        if not html:
            self._history_cache[horse_id] = None
            return None

        table = self._parse_result_table(html)
        if table is None or table.empty:
            self._history_cache[horse_id] = None
            return None

        table = table.copy()
        table["horse_id"] = horse_id
        self._history_cache[horse_id] = table.copy()
        return table

    # =================================================
    # 特徴量計算
    # =================================================

    def build(
        self,
        horse_id: str,
        horse_name: str | None = None,
        target_race_date: date | None = None,   # ← 追加
    ) -> Dict[str, Any]:
        """
        Args:
            horse_id:          netkeiba の馬ID
            horse_name:        馬名（表示用）
            target_race_date:  対象レースの日付。
                               指定すると rest_days（前走からの日数）を計算する。
        """
        table = self.scrape_horse(horse_id)
        if table is None or table.empty:
            return self._empty_features(horse_id, horse_name)

        # --- 着順（列11）: "中"/"除"等は NaN ---
        finish = pd.to_numeric(table.iloc[:, _FINISH_COL], errors="coerce")

        # --- 上り3F（列27）: 30〜50秒の範囲外は誤取得とみなし NaN ---
        agari = pd.to_numeric(table.iloc[:, _AGARI_COL], errors="coerce")
        agari = agari.where((agari >= _AGARI_MIN) & (agari <= _AGARI_MAX))

        # --- 日付（列0）: rest_days 計算用 ---
        date_strs = table.iloc[:, _DATE_COL].astype(str).tolist()
        horse_dates = [_parse_horse_page_date(s) for s in date_strs]

        # netkeiba は最新レースが先頭行
        finish_last5 = finish.head(5).dropna()
        finish_last3 = finish.head(3).dropna()
        agari_last5  = agari.head(5).dropna()

        avg_finish_last5 = (
            round(float(finish_last5.mean()), 2) if not finish_last5.empty else 0.0
        )
        avg_finish_last3 = (
            round(float(finish_last3.mean()), 2) if not finish_last3.empty else 0.0
        )
        avg_speed_index_last5 = (
            round(float(agari_last5.mean()), 2) if not agari_last5.empty else 0.0
        )

        finish_nonan = finish.dropna()
        last_finish = int(finish_nonan.iloc[0]) if not finish_nonan.empty else 0

        recent_form_score = (
            round(1.0 / (1.0 + avg_finish_last5), 4) if avg_finish_last5 > 0 else 0.0
        )

        # --- rest_days: 対象レース日 - 前走日 ---
        rest_days = 0
        if target_race_date is not None:
            # 対象レース日より前のレースを探す（リーケージ防止）
            last_race_date = None
            for d in horse_dates:
                if d is not None and d < target_race_date:
                    last_race_date = d
                    break  # 降順なので最初に見つかったものが最新の前走

            if last_race_date is not None:
                days = (target_race_date - last_race_date).days
                # 異常値（2年超）は除外
                if 0 < days <= _REST_DAYS_MAX:
                    rest_days = days

        return {
            "horse_id":              horse_id,
            "horse_name":            horse_name or "UNKNOWN",
            "avg_finish_last5":      avg_finish_last5,
            "avg_finish_last3":      avg_finish_last3,
            "avg_speed_index_last5": avg_speed_index_last5,
            "recent_form_score":     recent_form_score,
            "rest_days":             rest_days,
            "last_finish":           last_finish,
            "speed_index":           avg_speed_index_last5,
            "stamina_index":         avg_speed_index_last5,
            "acceleration_index":    avg_speed_index_last5,
            "consistency_index":     round(max(0.0, min(1.0, recent_form_score)), 4),
            "closing_speed":         avg_speed_index_last5,
        }

    # =================================================
    # レース DataFrame への一括付加
    # =================================================

    def attach_horse_history(self, race_df: pd.DataFrame) -> pd.DataFrame:
        """
        race_df の各行に馬過去成績特徴量を付加する。
        race_title 列があれば日付を抽出して rest_days を計算する。
        """
        df = race_df.copy()
        if "horse_id" not in df.columns:
            df["horse_id"] = None
        if "horse_name" not in df.columns:
            df["horse_name"] = None

        # race_title から対象レース日を行単位で計算（ベクトル化）
        target_dates = df.get("race_title")
        if target_dates is None:
            target_dates = pd.Series([None] * len(df), index=df.index)
        else:
            target_dates = target_dates.map(_parse_race_title_date)

        # horse_id を文字列化して空白を取り除く
        horse_ids = df["horse_id"].fillna("").astype(str).str.strip()
        horse_names = df["horse_name"]

        # ユニークな (horse_id, target_date) の組を作り、一度だけ特徴量を構築する
        unique_pairs = pd.DataFrame({
            "horse_id": horse_ids,
            "horse_name": horse_names,
            "target_date": target_dates,
        })
        unique_pairs = unique_pairs.drop_duplicates(subset=["horse_id", "target_date"]).reset_index(drop=True)

        features_map: Dict[str, Dict] = {}
        for row in unique_pairs.itertuples(index=False):
            hid = (row.horse_id or "").strip()
            hname = row.horse_name
            tdate = row.target_date
            key = f"{hid}|{tdate.isoformat() if isinstance(tdate, date) else ''}"
            features_map[key] = self.build(hid, hname, tdate)

        # 元の行順に対応する特徴量リストを作成
        histories = []
        for hid, hname, tdate in zip(horse_ids.tolist(), horse_names.tolist(), target_dates.tolist()):
            key = f"{(hid or '').strip()}|{tdate.isoformat() if isinstance(tdate, date) else ''}"
            hist = features_map.get(key)
            if hist is None:
                hist = self._empty_features(hid, hname)
            histories.append(hist)

        history_df = pd.DataFrame(histories)
        history_df = history_df.drop(
            columns=[c for c in ["horse_id", "horse_name"] if c in history_df.columns],
            errors="ignore",
        )

        merged = pd.concat([df.reset_index(drop=True), history_df.reset_index(drop=True)], axis=1)

        for col in ["horse_id", "horse_name"]:
            if col in merged.columns:
                merged[col] = merged[col].fillna("UNKNOWN")

        return merged

    # =================================================
    # フォールバック（スクレイプ失敗時）
    # =================================================

    def _empty_features(
        self, horse_id: str, horse_name: str | None = None
    ) -> Dict[str, Any]:
        return {
            "horse_id":              horse_id,
            "horse_name":            horse_name or "UNKNOWN",
            "avg_finish_last5":      0.0,
            "avg_finish_last3":      0.0,
            "avg_speed_index_last5": 0.0,
            "recent_form_score":     0.0,
            "rest_days":             0,
            "last_finish":           0,
            "speed_index":           0.0,
            "stamina_index":         0.0,
            "acceleration_index":    0.0,
            "consistency_index":     0.0,
            "closing_speed":         0.0,
        }
