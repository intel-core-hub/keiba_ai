# validation/walk_forward_validation.py

import numpy as np
import pandas as pd

from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from learning.brier_score import (
    BrierMonitor
)

from learning.performance_analyzer import (
    PerformanceAnalyzer
)


class WalkForwardValidator:
    """
    Walk Forward Validation

    目的:
    - 時系列検証
    - future leakage防止
    - survival durability確認
    - calibration stability確認

    最重要:
    「未来を見ない」
    """

    def __init__(

        self,

        train_window=3000,

        test_window=500,

        step_size=500,
    ):

        self.train_window = (
            train_window
        )

        self.test_window = (
            test_window
        )

        self.step_size = (
            step_size
        )

        self.results = []
        self.feature_names = []
        self.calibration_ratio = 0.2

    # =================================================
    # Data Preparation
    # =================================================

    def _sort_dataframe(self, dataframe):
        sort_cols = []
        if "race_date" in dataframe.columns:
            sort_cols.append("race_date")
        if "race_id" in dataframe.columns:
            sort_cols.append("race_id")
        if sort_cols:
            return dataframe.sort_values(sort_cols).reset_index(drop=True)
        return dataframe.reset_index(drop=True)

    def _split_into_blocks(self, dataframe):
        if "race_id" in dataframe.columns:
            return [group.copy() for _, group in dataframe.groupby("race_id", sort=False)]
        if "race_date" in dataframe.columns:
            return [group.copy() for _, group in dataframe.groupby("race_date", sort=False)]
        return [dataframe.iloc[[idx]].copy() for idx in range(len(dataframe))]

    def _feature_blacklist(self, target_col):
        return {
            "race_id",
            "horse_id",
            "horse_name",
            "race_date",
            "created_at",
            target_col,
            "target_place",
            "finishing_position",
            "odds",
            "final_odds",
            "closing_odds",
        }

    def _prepare_feature_frame(self, dataframe, target_col):
        frame = dataframe.copy()
        blacklist = self._feature_blacklist(target_col)

        feature_cols = []
        for column in frame.columns:
            if column in blacklist:
                continue
            try:
                pd.to_numeric(frame[column])
                feature_cols.append(column)
            except Exception:
                continue

        self.feature_names = feature_cols

        keep_cols = list(feature_cols)
        if target_col in frame.columns:
            keep_cols.append(target_col)

        return frame[keep_cols].copy()

    def _build_model(self):
        return Pipeline([
            (
                "imputer",
                SimpleImputer(strategy="median"),
            ),
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=200,
                    max_depth=6,
                    min_samples_leaf=8,
                    random_state=42,
                    class_weight="balanced",
                ),
            ),
        ])

    def _train_safe_model(self, train_df, target_col):
        prepared = self._prepare_feature_frame(train_df, target_col)
        if target_col not in prepared.columns:
            raise ValueError(f"target column missing: {target_col}")

        if not self.feature_names:
            raise ValueError("no usable numeric features after leakage filtering")

        blocks = self._split_into_blocks(prepared)
        if len(blocks) < 2:
            raise ValueError("walk-forward training requires at least 2 race/day blocks")

        cal_block_count = max(1, int(len(blocks) * self.calibration_ratio))
        cal_blocks = blocks[-cal_block_count:]
        base_blocks = blocks[:-cal_block_count]

        if len(base_blocks) == 0:
            base_blocks = blocks[:-1]
            cal_blocks = blocks[-1:]

        base_df = pd.concat(base_blocks, ignore_index=True)
        cal_df = pd.concat(cal_blocks, ignore_index=True)

        X_base = base_df[self.feature_names].apply(pd.to_numeric, errors="coerce")
        y_base = base_df[target_col].astype(int)
        X_cal = cal_df[self.feature_names].apply(pd.to_numeric, errors="coerce")
        y_cal = cal_df[target_col].astype(int)

        base_model = self._build_model()
        base_model.fit(X_base, y_base)

        use_calibration = y_cal.nunique() >= 2 and len(cal_df) >= 10
        if use_calibration:
            calibrated = CalibratedClassifierCV(
                estimator=base_model,
                method="sigmoid",
                cv="prefit",
            )
            calibrated.fit(X_cal, y_cal)
            model = calibrated
            cal_proba = model.predict_proba(X_cal)[:, 1]
        else:
            model = base_model
            cal_proba = base_model.predict_proba(X_cal)[:, 1]

        train_metrics = {
            "base_rows": len(base_df),
            "calibration_rows": len(cal_df),
            "calibration_brier": round(float(brier_score_loss(y_cal, cal_proba)), 6),
            "calibration_logloss": round(
                float(log_loss(y_cal, np.clip(cal_proba, 1e-6, 1 - 1e-6), labels=[0, 1])),
                6,
            ),
            "features": len(self.feature_names),
            "calibrated": use_calibration,
        }

        return model, train_metrics

    def _expected_calibration_error(self, predictions, targets, bins=10):
        if len(predictions) == 0:
            return 0.0

        probs = np.clip(np.asarray(predictions, dtype=float), 1e-6, 1 - 1e-6)
        hits = np.asarray(targets, dtype=float)
        edges = np.linspace(0.0, 1.0, bins + 1)
        total = len(probs)
        ece = 0.0

        for start, end in zip(edges[:-1], edges[1:]):
            if end == 1.0:
                mask = (probs >= start) & (probs <= end)
            else:
                mask = (probs >= start) & (probs < end)

            count = int(mask.sum())
            if count == 0:
                continue

            avg_prob = float(probs[mask].mean())
            avg_hit = float(hits[mask].mean())
            ece += (count / total) * abs(avg_prob - avg_hit)

        return float(ece)

    # =================================================
    # Chronological Validation
    # =================================================

    def validate(

        self,

        dataframe,

        target_col="target_win",
    ):

        dataframe = self._sort_dataframe(dataframe)
        blocks = self._split_into_blocks(dataframe)

        total_rows = len(blocks)

        current = self.train_window

        split_id = 0

        # =================================================
        # walk forward loop
        # =================================================

        while True:

            train_start = max(

                0,

                current
                - self.train_window
            )

            train_end = current

            test_end = (
                current
                + self.test_window
            )

            if test_end >= total_rows:
                break

            # -----------------------------------------
            # split
            # -----------------------------------------

            train_df = pd.concat(
                blocks[train_start:train_end],
                ignore_index=True,
            )

            test_df = pd.concat(
                blocks[train_end:test_end],
                ignore_index=True,
            )

            print("\n====================")
            print(
                f"SPLIT {split_id}"
            )
            print("====================")

            print(
                f"train: "
                f"{len(train_df)}"
            )

            print(
                f"test: "
                f"{len(test_df)}"
            )

            # -----------------------------------------
            # model
            # -----------------------------------------

            model, train_metrics = self._train_safe_model(
                train_df=train_df,
                target_col=target_col,
            )

            # -----------------------------------------
            # evaluation
            # -----------------------------------------

            report = self.evaluate_split(

                model=(
                    model
                ),

                test_df=test_df,

                split_id=split_id,

                target_col=(
                    target_col
                ),
            )

            report["train_metrics"] = (
                train_metrics
            )

            self.results.append(
                report
            )

            # -----------------------------------------
            # move forward
            # -----------------------------------------

            current += (
                self.step_size
            )

            split_id += 1

        return self.summary()

    # =================================================
    # Evaluate Split
    # =================================================

    def evaluate_split(

        self,

        model,

        test_df,

        split_id,

        target_col,
    ):

        brier_monitor = (
            BrierMonitor()
        )

        performance = (
            PerformanceAnalyzer()
        )

        predictions = []

        targets = []

        profits = []

        # =================================================
        # prediction loop
        # =================================================

        for _, row in test_df.iterrows():

            features = {
                name: row.get(name, np.nan)
                for name in self.feature_names
            }

            probability = float(
                model.predict_proba(
                    pd.DataFrame([features])
                )[0][1]
            )

            probability = float(
                np.clip(
                    probability,
                    0.01,
                    0.99,
                )
            )

            target = int(
                row[target_col]
            )

            predictions.append(
                probability
            )

            targets.append(
                target
            )

            # -----------------------------------------
            # brier
            # -----------------------------------------

            brier_monitor.record(

                probability=(
                    probability
                ),

                hit=target,

                odds=row.get(
                    "odds",
                    1,
                ),
            )

            # -----------------------------------------
            # pseudo profit
            # -----------------------------------------

            odds = pd.to_numeric(
                row.get("odds", np.nan),
                errors="coerce",
            )

            if pd.notna(odds) and odds > 1:
                implied = 1 / odds
                edge = probability - implied
            else:
                edge = -1

            # survival threshold
            if edge > 0.03:

                if target == 1:

                    profit = (
                        odds - 1
                    )

                else:

                    profit = -1

                profits.append(
                    profit
                )

                performance.record(
                    profit
                )

        # =================================================
        # metrics
        # =================================================

        avg_prediction = np.mean(predictions) if predictions else 0.0
        actual_rate = np.mean(targets) if targets else 0.0

        brier = (
            brier_monitor
            .current_brier()
        )

        try:
            logloss = log_loss(
                targets,
                np.clip(predictions, 1e-6, 1 - 1e-6),
                labels=[0, 1],
            )
        except Exception:
            logloss = None

        calibration_gap = float(abs(avg_prediction - actual_rate))
        ece = self._expected_calibration_error(predictions, targets)
        reliability = float(max(0.0, 1.0 - ece))

        perf = (
            performance.summary()
        )

        report = {

            "split_id":
                split_id,

            "predictions":
                len(predictions),

            "avg_prediction":
                round(
                    avg_prediction,
                    6,
                ),

            "actual_rate":
                round(
                    actual_rate,
                    6,
                ),

            "brier":
                round(
                    brier,
                    6,
                ),

            "logloss":
                round(
                    logloss,
                    6,
                ) if logloss is not None else None,

            "calibration_gap":
                round(
                    calibration_gap,
                    6,
                ),

            "ece":
                round(
                    ece,
                    6,
                ),

            "reliability":
                round(
                    reliability,
                    6,
                ),

            "profit":
                round(
                    np.sum(profits),
                    4,
                ),

            "roi":
                round(

                    np.mean(profits)

                    if len(profits) > 0
                    else 0,

                    6,
                ),

            "trades":
                len(profits),

            "max_drawdown":
                perf.get(
                    "max_drawdown",
                    None,
                ),
        }

        print(report)

        return report

    # =================================================
    # Stability Analysis
    # =================================================

    def stability_analysis(
        self,
    ):

        if len(self.results) == 0:

            return {}

        briers = [

            r["brier"]

            for r in self.results
        ]

        rois = [

            r["roi"]

            for r in self.results
        ]

        profits = [

            r["profit"]

            for r in self.results
        ]

        eces = [
            r.get("ece", 0.0)
            for r in self.results
            if r.get("ece") is not None
        ]

        reliabilities = [
            r.get("reliability", 0.0)
            for r in self.results
            if r.get("reliability") is not None
        ]

        # 前半と後半の brier 差を drift として扱う（fold 単位）
        half = max(1, len(briers) // 2)
        first_half = briers[:half]
        second_half = briers[half:]
        if len(second_half) == 0:
            drift_score = 0.0
        else:
            drift_score = float(abs(np.mean(first_half) - np.mean(second_half)))

        return {

            "brier_mean":
                round(
                    np.mean(briers),
                    6,
                ),

            "brier_std":
                round(
                    np.std(briers),
                    6,
                ),

            "roi_mean":
                round(
                    np.mean(rois),
                    6,
                ),

            "roi_std":
                round(
                    np.std(rois),
                    6,
                ),

            "profit_mean":
                round(
                    np.mean(profits),
                    6,
                ),

            "ece_mean":
                round(
                    np.mean(eces) if len(eces) > 0 else 0.0,
                    6,
                ),

            "reliability_mean":
                round(
                    np.mean(reliabilities) if len(reliabilities) > 0 else 0.0,
                    6,
                ),

            "drift_score":
                round(
                    drift_score,
                    6,
                ),

            "profitable_splits":
                int(sum(

                    1

                    for p in profits

                    if p > 0
                )),
        }

    def aggregate_reports(
        self,
        reports,
    ):

        if len(reports) == 0:
            return {
                "error": "no folds",
                "folds": 0,
                "splits": 0,
                "survival_score": 0.0,
                "results": [],
                "stability": {},
            }

        briers = [r.get("brier", 0.0) for r in reports if r.get("brier") is not None]
        losses = [r.get("logloss") for r in reports if r.get("logloss") is not None]
        eces = [r.get("ece", 0.0) for r in reports if r.get("ece") is not None]
        gaps = [r.get("calibration_gap", 0.0) for r in reports if r.get("calibration_gap") is not None]

        stability = self.stability_analysis()
        survival = self.survival_score()

        return {
            "folds": len(reports),
            "splits": len(reports),
            "mean_brier": round(float(np.mean(briers)) if len(briers) > 0 else 0.0, 6),
            "brier_mean": round(float(np.mean(briers)) if len(briers) > 0 else 0.0, 6),
            "std_brier": round(float(np.std(briers)) if len(briers) > 0 else 0.0, 6),
            "mean_log_loss": round(float(np.mean(losses)) if len(losses) > 0 else 0.0, 6),
            "mean_ece": round(float(np.mean(eces)) if len(eces) > 0 else 0.0, 6),
            "ece_mean": round(float(np.mean(eces)) if len(eces) > 0 else 0.0, 6),
            "mean_calibration_gap": round(float(np.mean(gaps)) if len(gaps) > 0 else 0.0, 6),
            "mean_reliability": round(float(np.mean([max(0.0, 1.0 - e) for e in eces])) if len(eces) > 0 else 0.0, 6),
            "reliability_mean": round(float(np.mean([max(0.0, 1.0 - e) for e in eces])) if len(eces) > 0 else 0.0, 6),
            "drift_score": stability.get("drift_score", 0.0),
            "survival_score": survival,
            "stability": stability,
            "results": reports,
            "fold_reports": reports,
        }

    def phase2_payload(self, report=None):

        source = report if isinstance(report, dict) else self.summary()
        stability = source.get("stability", {}) if isinstance(source.get("stability", {}), dict) else {}

        return {
            "mean_brier": source.get("mean_brier", source.get("brier_mean", stability.get("brier_mean", 0.0))),
            "mean_ece": source.get("mean_ece", source.get("ece_mean", stability.get("ece_mean", 0.0))),
            "mean_reliability": source.get("mean_reliability", source.get("reliability_mean", stability.get("reliability_mean", 0.0))),
            "drift_score": source.get("drift_score", stability.get("drift_score", 0.0)),
            "survival_score": source.get("survival_score", 0.0),
            "roi_mean": stability.get("roi_mean", 0.0),
            "roi_std": stability.get("roi_std", 0.0),
        }

    # =================================================
    # Survival Score
    # =================================================

    def survival_score(
        self,
    ):

        if len(self.results) == 0:
            return 0

        stable_brier = 0

        stable_roi = 0

        low_drawdown = 0

        for r in self.results:

            # -----------------------------------------
            # calibration
            # -----------------------------------------

            if r["brier"] < 0.25:
                stable_brier += 1

            # -----------------------------------------
            # roi
            # -----------------------------------------

            if r["roi"] > -0.05:
                stable_roi += 1

            # -----------------------------------------
            # drawdown
            # -----------------------------------------

            dd = r.get(
                "max_drawdown",
                1,
            )

            if dd < 0.3:
                low_drawdown += 1

        total = len(self.results)

        score = np.mean([

            stable_brier / total,

            stable_roi / total,

            low_drawdown / total,
        ])

        return round(
            score,
            6,
        )

    # =================================================
    # Summary
    # =================================================

    def summary(
        self,
    ):

        report = self.aggregate_reports(self.results)

        print("\n====================")
        print("WALK FORWARD SUMMARY")
        print("====================")

        print(
            "splits:",
            report["splits"]
        )

        print(
            "survival_score:",
            report[
                "survival_score"
            ]
        )

        print(
            "\nStability:"
        )

        print(
            report.get("stability", {})
        )

        return report


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    try:

        df = pd.read_csv(
            "data/processed/historical_dataset.csv"
        )

        validator = (
            WalkForwardValidator(

                train_window=3000,

                test_window=500,

                step_size=500,
            )
        )

        report = (
            validator.validate(
                df
            )
        )

    except Exception as e:

        print(
            "[WF ERROR]",
            e,
        )