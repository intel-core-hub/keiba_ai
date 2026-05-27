# data/historical_dataset.py

import os
import sys
import glob
import pandas as pd
import numpy as np

# schemas/ はプロジェクト内のモジュール。
# site-packages に同名パッケージが入っている場合に備えて
# プロジェクトルートを sys.path の先頭に追加する。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from schemas.race_schema import (
    HorseFeatures,
    RaceSchemaUtils,
)


class HistoricalDatasetBuilder:
    """
    Historical Dataset Pipeline

    目的:
    - 生データ統合
    - schema統一
    - leakage防止
    - training dataset生成
    - walk-forward準備

    最重要:
    「未来情報を混ぜない」
    """

    def __init__(
        self,
        raw_dir="data/raw",
        processed_dir="data/processed",
    ):
        self.raw_dir = raw_dir
        self.processed_dir = processed_dir

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.processed_dir, exist_ok=True)

    # =================================================
    # Load CSV Files
    # =================================================

    def load_raw_csvs(self):
        files = glob.glob(os.path.join(self.raw_dir, "*.csv"))

        if len(files) == 0:
            raise FileNotFoundError("No raw csv files found")

        dfs = []

        for f in files:
            # 旧フォーマット（日本語列名）は除外
            if os.path.basename(f).startswith("phase4_range_"):
                continue

            try:
                df = pd.read_csv(f)

                for col in ["race_id", "horse_id"]:
                    if col in df.columns:
                        numeric = pd.to_numeric(df[col], errors="coerce")
                        if numeric.notna().any():
                            df[col] = numeric.apply(
                                lambda v: str(int(v)) if pd.notna(v) else ""
                            )
                        else:
                            df[col] = df[col].astype(str)

                df["source_file"] = os.path.basename(f)
                dfs.append(df)

            except Exception as e:
                print("[LOAD ERROR]", f, e)

        if len(dfs) == 0:
            raise ValueError("No valid csv loaded")

        return pd.concat(dfs, ignore_index=True)

    # =================================================
    # Normalize Columns
    # =================================================

    def normalize_columns(self, df):
        """列名統一・scraper差異吸収"""
        mapping = {
            "単勝":   "odds",
            "odds":   "odds",
            "horse":  "horse_name",
            "馬名":   "horse_name",
            "着順":   "finishing_position",
            "人気":   "favorite_rank",
            "race":   "race_id",
            "race_id":"race_id",
        }

        renamed = {c: mapping[c] for c in df.columns if c in mapping}
        return df.rename(columns=renamed)

    # =================================================
    # Extract Race Date          ← 追加
    # =================================================

    def extract_race_date(self, df):
        """
        race_date を以下の優先順位で復元する:

        1. race_title に「YYYY年M月D日」が含まれる → そこから取得（最優先）
           例: "3歳未勝利｜2024年6月1日 | ..." → "20240601"

        2. race_title がない or マッチしない → UNKNOWN
           → 時系列ソート時に末尾に置かれる

        ※ race_id の先頭8桁は「年+場コード+回+日」であり
          「年月日」ではないため直接変換できない。
        """
        import re

        df = df.copy()

        def from_title(title):
            if not isinstance(title, str):
                return "UNKNOWN"
            m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', title)
            if m:
                y, mo, d = m.groups()
                return f"{y}{int(mo):02d}{int(d):02d}"
            return "UNKNOWN"

        if "race_title" in df.columns:
            df["race_date"] = df["race_title"].apply(from_title)
        else:
            df["race_date"] = "UNKNOWN"

        valid   = (df["race_date"] != "UNKNOWN").sum()
        invalid = len(df) - valid
        print(f"  race_date 復元: 有効={valid}, 無効={invalid}")

        return df

    # =================================================
    # Basic Cleaning
    # =================================================

    def clean_dataframe(self, df):
        df = df.loc[:, ~df.columns.duplicated()].copy()
        df = df.drop_duplicates()

        if "odds" in df:
            df["odds"] = pd.to_numeric(df["odds"], errors="coerce")
            df = df[df["odds"] > 0]

        if "finishing_position" in df:
            df["finishing_position"] = pd.to_numeric(
                df["finishing_position"], errors="coerce"
            )

        if "favorite_rank" in df:
            df["favorite_rank"] = pd.to_numeric(
                df["favorite_rank"], errors="coerce"
            )

        if "horse_name" in df:
            df = df[df["horse_name"].notnull()]

        if "race_id" in df:
            df = df[df["race_id"].notnull()]

        return df.reset_index(drop=True)

    # =================================================
    # Build Targets
    # =================================================

    def build_targets(self, df):
        """未来情報ではなく結果ラベル生成"""
        if "finishing_position" not in df:
            return df

        df["target_win"] = (df["finishing_position"] == 1).astype(int)
        df["target_place"] = (df["finishing_position"] <= 3).astype(int)

        return df

    # =================================================
    # Feature Engineering
    # =================================================

    def feature_engineering(self, df):
        """survival oriented features"""
        df = df.copy()

        defaults = {
            "track":              "UNKNOWN",
            "distance":           0,
            "surface":            "UNKNOWN",
            "weather":            "UNKNOWN",
            "gate":               0,
            "field_size":         0,
            "horse_id":           "UNKNOWN",
            "horse_name":         "UNKNOWN",
            "odds":               np.nan,
            "favorite_rank":      np.nan,
            "speed_index":        0.0,
            "stamina_index":      0.0,
            "acceleration_index": 0.0,
            "consistency_index":  0.5,
            "closing_speed":      0.0,
            "last_finish":        0,
            "avg_finish_last5":   np.nan,
            "recent_form_score":  0.0,
            "rest_days":          0,
            "weight_change":      0.0,
            "jockey_score":       0.0,
            "trainer_score":      0.0,
            "stable_score":       0.0,
            "market_support":     np.nan,
            "odds_value":         np.nan,
            "public_confidence":  0.0,
            "track_affinity":     0.5,
            "distance_affinity":  0.5,
            "weather_affinity":   0.5,
            "pace_affinity":      0.5,
            "rank_score":         0.0,
            "composite_score":    0.0,
            "volatility_score":   0.0,
            "uncertainty_score":  0.0,
        }

        # race_date はここではデフォルト設定しない
        # → extract_race_date() が先に処理している

        for column, value in defaults.items():
            if column not in df.columns:
                df[column] = value

        if "odds" in df:
            df["market_support"] = 1 / df["odds"]
            df["odds_value"] = df["market_support"]

        if "favorite_rank" in df:
            df["rank_score"] = 1.0 / (1.0 + df["favorite_rank"].fillna(0))

        if "finishing_position" in df:
            df["hit"] = (df["finishing_position"] == 1).astype(int)

        # -----------------------------------------
        # Per-horse temporal features (avoid leakage)
        # Ensure dataset is already sorted chronologically before calling this
        # -----------------------------------------
        if "finishing_position" in df.columns:
            if "horse_id" in df.columns:
                try:
                    grp = df.groupby("horse_id")["finishing_position"]
                    df["last_finish"] = grp.apply(
                        lambda s: s.shift(1)
                    ).reset_index(level=0, drop=True).fillna(0).astype(int)

                    # recompute avg finish over last 5 races (past only)
                    df["avg_finish_last5"] = grp.apply(
                        lambda s: s.shift(1).rolling(5, min_periods=1).mean()
                    ).reset_index(level=0, drop=True)
                except Exception:
                    # fallback to safe default
                    df["last_finish"] = df["finishing_position"].shift(1).fillna(0).astype(int)
                    if "avg_finish_last5" not in df.columns:
                        df["avg_finish_last5"] = np.nan
            else:
                df["last_finish"] = df["finishing_position"].shift(1).fillna(0).astype(int)
                if "avg_finish_last5" not in df.columns:
                    df["avg_finish_last5"] = np.nan

        # If avg_finish_last5 present (either recomputed or from source), update recent_form_score
        if "avg_finish_last5" in df.columns:
            df["avg_finish_last5"] = pd.to_numeric(
                df["avg_finish_last5"], errors="coerce"
            )
            df["recent_form_score"] = np.where(
                df["avg_finish_last5"].notna(),
                1.0 / (1.0 + df["avg_finish_last5"].clip(lower=0)),
                df["recent_form_score"],
            )

        # Recompute avg_speed_index_last5 per-horse from past-only speed_index values
        if "avg_speed_index_last5" in df.columns and "speed_index" in df.columns:
            try:
                grp_si = df.groupby("horse_id")["speed_index"]
                df["avg_speed_index_last5"] = grp_si.apply(
                    lambda s: s.shift(1).rolling(5, min_periods=1).mean()
                ).reset_index(level=0, drop=True)
                df["avg_speed_index_last5"] = pd.to_numeric(
                    df["avg_speed_index_last5"], errors="coerce"
                )
                df["speed_index"] = np.where(
                    df["avg_speed_index_last5"].notna(),
                    df["avg_speed_index_last5"],
                    df["speed_index"],
                )
            except Exception:
                # fallback: leave existing values
                df["avg_speed_index_last5"] = pd.to_numeric(
                    df.get("avg_speed_index_last5", pd.Series()), errors="coerce"
                )

        if "race_time" in df:
            df["recent_form_score"] = df["recent_form_score"].fillna(0.0)

        if "horse_weight_diff" in df:
            df["weight_change"] = df["horse_weight_diff"].fillna(0.0)

        if "age" in df and "horse_weight" in df:
            df["rest_days"] = df["rest_days"].fillna(0)

        # Note: Do NOT normalize numeric features here using global statistics
        # (e.g., min/max across the entire dataset). That leaks future information.
        # Per-fold scaling (StandardScaler in model pipelines) should be used.

        if "odds" in df:
            df["uncertainty_score"] = np.clip(df["odds"] / 30, 0, 1)

        if "avg_finish_last5" in df:
            df["volatility_score"] = np.clip(df["avg_finish_last5"] / 18, 0, 1)

        components = [
            c for c in ["speed_index", "recent_form_score",
                         "jockey_score", "trainer_score", "market_support"]
            if c in df
        ]
        if components:
            df["composite_score"] = df[components].mean(axis=1)

        if "form" not in df.columns:
            df["form"] = df["recent_form_score"]

        if "avg_speed_index_last5" in df.columns:
            df["composite_score"] = np.where(
                df["composite_score"].eq(0.0),
                (df["speed_index"] + df["avg_speed_index_last5"]) / 2,
                df["composite_score"],
            )

        if "hit" not in df.columns and "target_win" in df.columns:
            df["hit"] = df["target_win"].fillna(0).astype(int)

        return df

    # =================================================
    # Schema Validation
    # =================================================

    def schema_validate(self, df):
        required = RaceSchemaUtils.required_fields()
        missing = [r for r in required if r not in df.columns]

        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        return True

    # =================================================
    # Leakage Check
    # =================================================

    def leakage_check(self, df):
        leakage = RaceSchemaUtils.detect_leakage(df.columns)

        allowed = [
            "target_win", "target_place", "finishing_position",
            "last_finish", "avg_finish_last5",
            "avg_speed_index_last5", "recent_form_score",
        ]

        dangerous = [x for x in leakage if x not in allowed]

        if dangerous:
            print("[WARNING] Potential leakage:", dangerous)

        return dangerous

    # =================================================
    # Sort Chronologically
    # =================================================

    def chronological_sort(self, df):
        if "race_date" not in df:
            return df

        # UNKNOWN は末尾に
        unknown_mask = df["race_date"] == "UNKNOWN"
        df_known   = df[~unknown_mask].sort_values("race_date")
        df_unknown = df[unknown_mask]

        return pd.concat(
            [df_known, df_unknown], ignore_index=True
        )

    # =================================================
    # Finalize Dataset
    # =================================================

    def finalize(self, df):
        # IMPORTANT: do NOT impute numeric columns using global statistics here.
        # Imputing with medians across the full dataset leaks future information
        # into training. Leave numeric NaNs intact and rely on per-fold
        # imputers (e.g., SimpleImputer in model pipelines) during training.

        object_cols = df.select_dtypes(include=["object"]).columns
        for c in object_cols:
            df[c] = df[c].fillna("UNKNOWN")

        return df

    # =================================================
    # Save Dataset
    # =================================================

    def save_dataset(self, df, filename="historical_dataset.csv"):
        path = os.path.join(self.processed_dir, filename)
        df.to_csv(path, index=False)
        print(f"[SAVED] {path}")
        return path

    # =================================================
    # Build Full Pipeline
    # =================================================

    def build(self):
        print("\n[LOAD RAW]")
        df = self.load_raw_csvs()
        print("rows:", len(df))

        print("\n[NORMALIZE]")
        df = self.normalize_columns(df)

        print("\n[RACE DATE]")       # ← 追加
        df = self.extract_race_date(df)

        print("\n[CLEAN]")
        df = self.clean_dataframe(df)
        print("rows:", len(df))

        print("\n[TARGET]")
        df = self.build_targets(df)

        print("\n[SORT]")
        # Sort chronologically before feature engineering to ensure
        # groupby/shift/rolling operate on past-only data
        df = self.chronological_sort(df)

        print("\n[FEATURE]")
        df = self.feature_engineering(df)

        print("\n[SCHEMA]")
        self.schema_validate(df)

        print("\n[LEAKAGE]")
        self.leakage_check(df)

        print("\n[FINALIZE]")
        df = self.finalize(df)

        print("\n[SAVE]")
        self.save_dataset(df)

        print("\n[DONE]")
        print("final rows:", len(df))
        print("columns:", len(df.columns))

        # race_date の確認
        if "race_date" in df.columns:
            valid = (df["race_date"] != "UNKNOWN").sum()
            print(f"race_date 有効: {valid}/{len(df)} 行")
            print(f"  期間: {df[df['race_date']!='UNKNOWN']['race_date'].min()}"
                  f" 〜 {df[df['race_date']!='UNKNOWN']['race_date'].max()}")

        return df

    # =================================================
    # Dataset Diagnostics
    # =================================================

    def diagnostics(self, df):
        return {
            "rows":          len(df),
            "columns":       len(df.columns),
            "missing_total": int(df.isnull().sum().sum()),
            "win_rate":      round(df["target_win"].mean(), 4)
                             if "target_win" in df else None,
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":
    builder = HistoricalDatasetBuilder()

    try:
        df = builder.build()
        print(builder.diagnostics(df))

    except Exception as e:
        print("[DATASET ERROR]", e)
