# learning/walk_forward.py

import pandas as pd
import numpy as np

from sklearn.linear_model import (
    LogisticRegression
)

from sklearn.calibration import (
    CalibratedClassifierCV
)

from sklearn.metrics import (
    brier_score_loss,
    log_loss,
)


class WalkForwardValidator:
    """
    Walk Forward Validation

    目的:
    - 時系列検証
    - drift耐性確認
    - calibration stability
    - regime耐性

    重要:
    「一回当たる」
    ではなく
    「壊れず生き残る」
    """

    def __init__(self):

        self.feature_columns = [
            "rank_score",
            "speed_index",
            "odds_value",
            "form",
        ]

    # =================================================
    # Dataset
    # =================================================

    def load_dataset(
        self,
        path,
    ):

        return pd.read_csv(path)

    # =================================================
    # Feature Build
    # =================================================

    def build_xy(
        self,
        df,
    ):

        X = df[
            self.feature_columns
        ].copy()

        X = X.fillna(0)

        y = df["hit"].astype(int)

        return X, y

    # =================================================
    # Single Fold
    # =================================================

    def run_fold(
        self,
        train_df,
        test_df,
    ):

        X_train, y_train = (
            self.build_xy(train_df)
        )

        X_test, y_test = (
            self.build_xy(test_df)
        )

        # -----------------------------------------
        # model
        # -----------------------------------------

        base_model = LogisticRegression(
            max_iter=1000
        )

        model = CalibratedClassifierCV(
            base_model,
            method="sigmoid",
            cv=3,
        )

        model.fit(
            X_train,
            y_train,
        )

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

        actual = np.mean(y_test)

        calibration_gap = abs(
            avg_prob - actual
        )

        return {
            "brier": float(brier),
            "log_loss": float(ll),
            "avg_probability": float(avg_prob),
            "actual_rate": float(actual),
            "calibration_gap": float(
                calibration_gap
            ),
        }

    # =================================================
    # Walk Forward
    # =================================================

    def validate(
        self,
        dataset_path,
        min_train_size=1000,
        test_window=200,
        step_size=200,
    ):

        df = self.load_dataset(
            dataset_path
        )

        reports = []

        start = min_train_size

        while (
            start + test_window
            <= len(df)
        ):

            # -----------------------------------------
            # split
            # -----------------------------------------

            train_df = df.iloc[:start]

            test_df = df.iloc[
                start:start+test_window
            ]

            # -----------------------------------------
            # fold
            # -----------------------------------------

            report = self.run_fold(
                train_df,
                test_df,
            )

            report["train_size"] = len(
                train_df
            )

            report["test_size"] = len(
                test_df
            )

            reports.append(report)

            start += step_size

        return self.aggregate_reports(
            reports
        )

    # =================================================
    # Aggregate
    # =================================================

    def aggregate_reports(
        self,
        reports,
    ):

        if len(reports) == 0:

            return {
                "error": "no folds"
            }

        briers = [
            r["brier"]
            for r in reports
        ]

        gaps = [
            r["calibration_gap"]
            for r in reports
        ]

        losses = [
            r["log_loss"]
            for r in reports
        ]

        # -----------------------------------------
        # stability
        # -----------------------------------------

        brier_std = np.std(briers)

        calibration_std = np.std(gaps)

        # -----------------------------------------
        # drift estimate
        # -----------------------------------------

        drift = abs(
            np.mean(briers[:len(briers)//2])
            -
            np.mean(briers[len(briers)//2:])
        )

        # -----------------------------------------
        # survival score
        # -----------------------------------------

        survival_score = 1.0

        if np.mean(briers) > 0.22:
            survival_score *= 0.7

        if brier_std > 0.03:
            survival_score *= 0.8

        if calibration_std > 0.03:
            survival_score *= 0.8

        if drift > 0.03:
            survival_score *= 0.7

        return {

            "folds": len(reports),

            "mean_brier": round(
                np.mean(briers),
                4,
            ),

            "std_brier": round(
                brier_std,
                4,
            ),

            "mean_log_loss": round(
                np.mean(losses),
                4,
            ),

            "mean_calibration_gap": round(
                np.mean(gaps),
                4,
            ),

            "calibration_stability": round(
                calibration_std,
                4,
            ),

            "drift_score": round(
                drift,
                4,
            ),

            "survival_score": round(
                survival_score,
                4,
            ),

            "fold_reports": reports,
        }