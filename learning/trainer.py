# learning/trainer.py

import pandas as pd
import numpy as np
import joblib

from pathlib import Path

from sklearn.model_selection import (
    train_test_split
)

from sklearn.metrics import (
    brier_score_loss,
    log_loss,
)

from learning.model_factory import build_boosted_pipeline


class SurvivalModelTrainer:
    """
    Survival-Oriented Trainer

    目的:
    - 高精度ではなく安定性
    - calibration重視
    - overfit抑制
    - drift検知可能化

    方針:
    「市場より少し良い」
    を長く維持する
    """

    def __init__(
        self,
        model_path="models/prediction_model.pkl",
    ):

        self.model_path = Path(model_path)

        self.model = None

        self.feature_columns = None

    # =================================================
    # Load Dataset
    # =================================================

    def load_dataset(
        self,
        path,
    ):

        df = pd.read_csv(path)

        return df

    # =================================================
    # Feature Build
    # =================================================

    def build_features(
        self,
        df,
    ):

        """
        最低限特徴量

        重要:
        最初は少なくていい
        """

        df = df.copy()

        if "hit" not in df.columns:
            if "target_win" in df.columns:
                df["hit"] = df["target_win"].fillna(0).astype(int)
            elif "finishing_position" in df.columns:
                df["hit"] = (df["finishing_position"] == 1).astype(int)
            else:
                df["hit"] = 0

        if "odds_value" not in df.columns and "odds" in df.columns:
            df["odds_value"] = 1.0 / df["odds"].replace(0, np.nan)

        if "form" not in df.columns:
            if "recent_form_score" in df.columns:
                df["form"] = df["recent_form_score"]
            elif "avg_finish_last5" in df.columns:
                df["form"] = 1.0 / (1.0 + df["avg_finish_last5"].fillna(5.0))
            else:
                df["form"] = 0.0

        if "rank_score" not in df.columns:
            if "favorite_rank" in df.columns:
                df["rank_score"] = 1.0 / (1.0 + df["favorite_rank"].fillna(0))
            else:
                df["rank_score"] = 0.0

        if "speed_index" not in df.columns:
            if "avg_speed_index_last5" in df.columns:
                df["speed_index"] = df["avg_speed_index_last5"]
            else:
                df["speed_index"] = 0.0

        features = [
            "rank_score",
            "speed_index",
            "odds_value",
            "form",
        ]

        self.feature_columns = features

        X = df[features].copy()
        X = X.fillna(0)

        y = df["hit"].astype(int)

        return X, y

    # =================================================
    # Temporal Split
    # =================================================

    def temporal_split(
        self,
        X,
        y,
        test_size=0.2,
    ):

        """
        時系列破壊防止

        shuffleしない
        """

        split_idx = int(
            len(X) * (1 - test_size)
        )

        X_train = X.iloc[:split_idx]
        X_test = X.iloc[split_idx:]

        y_train = y.iloc[:split_idx]
        y_test = y.iloc[split_idx:]

        return (
            X_train,
            X_test,
            y_train,
            y_test,
        )

    # =================================================
    # Train
    # =================================================

    def train(
        self,
        dataset_path,
    ):

        # -----------------------------------------
        # load
        # -----------------------------------------

        df = self.load_dataset(
            dataset_path
        )

        X, y = self.build_features(df)

        (
            X_train,
            X_test,
            y_train,
            y_test,
        ) = self.temporal_split(X, y)

        # -----------------------------------------
        # base model
        # -----------------------------------------

        class_counts = y_train.value_counts()
        min_class_count = int(class_counts.min()) if not class_counts.empty else 0

        if min_class_count < 2 or len(X_train) < 6:
            # Small sample fallback: fit the base model directly when calibration is not stable.
            model = build_boosted_pipeline(cv=2, calibrated=False, use_scaler=False)
        else:
            cv_folds = max(2, min(3, min_class_count))
            model = build_boosted_pipeline(cv=cv_folds, calibrated=True, use_scaler=False)

        model.fit(
            X_train,
            y_train,
        )

        # -----------------------------------------
        # predict
        # -----------------------------------------

        probs = model.predict_proba(
            X_test
        )[:, 1]

        # -----------------------------------------
        # metrics
        # -----------------------------------------

        brier = brier_score_loss(
            y_test,
            probs,
        )

        ll = log_loss(
            y_test,
            probs,
        )

        avg_prob = np.mean(probs)
        actual_rate = np.mean(y_test)

        calibration_gap = abs(
            avg_prob - actual_rate
        )

        # -----------------------------------------
        # drift estimate
        # -----------------------------------------

        first_half = probs[
            :len(probs)//2
        ]

        second_half = probs[
            len(probs)//2:
        ]

        drift = abs(
            np.mean(first_half)
            - np.mean(second_half)
        )

        # -----------------------------------------
        # save
        # -----------------------------------------

        self.model = model

        self.save_model()

        # -----------------------------------------
        # report
        # -----------------------------------------

        report = {
            "samples": len(df),

            "train_size": len(X_train),
            "test_size": len(X_test),

            "brier": round(
                brier,
                4,
            ),

            "log_loss": round(
                ll,
                4,
            ),

            "avg_probability": round(
                avg_prob,
                4,
            ),

            "actual_hit_rate": round(
                actual_rate,
                4,
            ),

            "calibration_gap": round(
                calibration_gap,
                4,
            ),

            "prediction_drift": round(
                drift,
                4,
            ),
        }

        return report

    # =================================================
    # Save
    # =================================================

    def save_model(self):

        payload = {
            "model": self.model,
            "features": self.feature_columns,
        }

        self.model_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        joblib.dump(
            payload,
            self.model_path,
        )

    # =================================================
    # Load
    # =================================================

    def load_model(self):

        payload = joblib.load(
            self.model_path
        )

        self.model = payload["model"]

        self.feature_columns = payload[
            "features"
        ]

        return self.model

    # =================================================
    # Predict
    # =================================================

    def predict(
        self,
        features: dict,
    ):

        if self.model is None:
            self.load_model()

        x = pd.DataFrame([
            {
                c: features.get(c, 0)
                for c in self.feature_columns
            }
        ])

        prob = self.model.predict_proba(
            x
        )[0][1]

        # safety clamp
        prob = max(
            0.01,
            min(prob, 0.95)
        )

        return float(prob)