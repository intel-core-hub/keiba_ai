# core/adaptation/auto_retrainer.py

import os
import time
import shutil
import pandas as pd

from datetime import datetime

from core.prediction.predictor import (
    Predictor
)

from core.prediction.regime_detector import (
    RegimeDetector
)

from validation.walk_forward_validation import (
    WalkForwardValidator
)

from core.execution.calibration_refit import CalibrationRefitJob


class AutoRetrainer:
    """
    Self-Healing Retraining System

    目的:
    - drift recovery
    - self repair
    - automatic recalibration
    - safe model replacement

    最重要:
    「壊れても復帰する」
    """

    def __init__(

        self,

        dataset_path=(
            "data/processed/"
            "historical_dataset.csv"
        ),

        model_path=(
            "models/predictor.pkl"
        ),

        backup_dir="models/backups",
        bets_log_path="logs/bets.csv",
        calibrator_path="models/calibrator_state.json",
        min_calibration_samples=100,
    ):

        self.dataset_path = (
            dataset_path
        )

        self.model_path = (
            model_path
        )

        self.backup_dir = (
            backup_dir
        )

        os.makedirs(

            self.backup_dir,

            exist_ok=True,
        )

        # =================================================
        # thresholds
        # =================================================

        self.max_brier = 0.25

        self.max_ece = 0.08

        self.max_drift = 0.03

        self.min_reliability = 0.88

        self.min_survival = 0.45

        self.min_rows = 1000

        # =================================================
        # state
        # =================================================

        self.last_retrain = None

        self.last_result = None

        self.calibration_job = CalibrationRefitJob(
            bets_log_path=bets_log_path,
            calibrator_path=calibrator_path,
            min_samples=min_calibration_samples,
        )

        self.last_calibration_result = None

    # =================================================
    # Backup Current Model
    # =================================================

    def backup_current_model(
        self,
    ):

        if not os.path.exists(
            self.model_path
        ):

            return None

        timestamp = datetime.utcnow().strftime(
            "%Y%m%d_%H%M%S"
        )

        backup_path = os.path.join(

            self.backup_dir,

            f"predictor_{timestamp}.pkl",
        )

        shutil.copy2(

            self.model_path,

            backup_path,
        )

        print(
            f"[BACKUP] "
            f"{backup_path}"
        )

        return backup_path

    # =================================================
    # Load Dataset
    # =================================================

    def load_dataset(
        self,
    ):

        if not os.path.exists(
            self.dataset_path
        ):

            raise FileNotFoundError(

                self.dataset_path
            )

        df = pd.read_csv(
            self.dataset_path
        )

        if len(df) < self.min_rows:

            raise ValueError(

                "dataset too small"
            )

        return df

    # =================================================
    # Train Candidate Model
    # =================================================

    def train_candidate(
        self,
        df,
    ):

        candidate_path = (
            "models/"
            "candidate_predictor.pkl"
        )

        predictor = Predictor(
            model_path=candidate_path
        )

        metrics = predictor.train(
            df
        )

        return predictor, metrics

    # =================================================
    # Walk Forward Validation
    # =================================================

    def validate_candidate(
        self,
        df,
    ):

        validator = (
            WalkForwardValidator(

                train_window=3000,

                test_window=500,

                step_size=500,
            )
        )

        report = (
            validator.validate(df)
        )

        return report

    # =================================================
    # Safety Check
    # =================================================

    def safety_check(
        self,
        validation_report,
    ):

        survival = validation_report.get(
            "survival_score",
            0,
        )

        stability = validation_report.get(
            "stability",
            {},
        )

        brier = validation_report.get(
            "mean_brier",
            stability.get(
                "brier_mean",
                validation_report.get(
                    "brier",
                    validation_report.get(
                        "brier_mean",
                        1,
                    ),
                ),
            ),
        )

        ece = validation_report.get(
            "mean_ece",
            stability.get(
                "ece_mean",
                validation_report.get(
                    "ece",
                    validation_report.get(
                        "ece_mean",
                        1,
                    ),
                ),
            ),
        )

        drift = validation_report.get(
            "drift_score",
            stability.get(
                "drift_score",
                1,
            ),
        )

        reliability = validation_report.get(
            "mean_reliability",
            stability.get(
                "reliability_mean",
                validation_report.get(
                    "reliability",
                    validation_report.get(
                        "reliability_mean",
                        0,
                    ),
                ),
            ),
        )

        # =================================================
        # checks
        # =================================================

        if survival < self.min_survival:

            return False, (
                "survival too low"
            )

        if brier > self.max_brier:

            return False, (
                "brier too high"
            )

        if ece > self.max_ece:

            return False, (
                "ece too high"
            )

        if drift > self.max_drift:

            return False, (
                "drift too high"
            )

        if reliability < self.min_reliability:

            return False, (
                "reliability too low"
            )

        return True, "PASS"

    # =================================================
    # Promote Candidate
    # =================================================

    def promote_candidate(
        self,
    ):

        candidate = (
            "models/"
            "candidate_predictor.pkl"
        )

        if not os.path.exists(
            candidate
        ):

            raise FileNotFoundError(
                candidate
            )

        shutil.copy2(

            candidate,

            self.model_path,
        )

        print(
            "\n[PROMOTED]"
        )

        print(
            "new model:",
            self.model_path,
        )

    def retrain(
        self,
    ):

        print("\n====================")
        print("AUTO RETRAIN")
        print("====================")

        # =================================================
        # backup
        # =================================================

        backup_path = (
            self.backup_current_model()
        )

        try:

            # =================================================
            # dataset
            # =================================================

            print(
                "\n[LOAD DATASET]"
            )

            df = self.load_dataset()

            print(
                "rows:",
                len(df)
            )

            # =================================================
            # train
            # =================================================

            print(
                "\n[TRAIN]"
            )

            predictor, metrics = (
                self.train_candidate(
                    df
                )
            )

            print(metrics)

            # =================================================
            # validate
            # =================================================

            print(
                "\n[VALIDATE]"
            )

            validation = (
                self.validate_candidate(
                    df
                )
            )

            # =================================================
            # safety gate
            # =================================================

            print(
                "\n[SAFETY CHECK]"
            )

            safe, reason = (
                self.safety_check(
                    validation
                )
            )

            print(
                "safe:",
                safe
            )

            print(
                "reason:",
                reason
            )

            # =================================================
            # reject
            # =================================================

            if not safe:

                print(
                    "\n[REJECTED]"
                )

                self.last_result = {

                    "status":
                        "REJECTED",

                    "reason":
                        reason,

                    "validation":
                        validation,
                }

                return self.last_result

            # =================================================
            # promote
            # =================================================

            self.promote_candidate()

            self.last_retrain = (
                datetime.utcnow()
                .isoformat()
            )

            self.last_result = {

                "status":
                    "PROMOTED",

                "metrics":
                    metrics,

                "validation":
                    validation,

                "backup":
                    backup_path,

                "timestamp":
                    self.last_retrain,
            }

            print(
                "\n[SUCCESS]"
            )

            return self.last_result

        except Exception as e:

            print(
                "\n[RETRAIN ERROR]"
            )

            print(e)

            self.last_result = {

                "status":
                    "ERROR",

                "error":
                    str(e),
            }

            return self.last_result

    # =================================================
    # Drift Trigger
    # =================================================

    def should_retrain(
        self,
        regime_detector,
    ):

        regime = (
            regime_detector
            .current_regime
        )

        dangerous = {

            "DRIFT",

            "COLLAPSE",
        }

        return regime in dangerous

    # =================================================
    # Recovery Attempt
    # =================================================

    def maybe_recalibrate(
        self,
        *,
        force: bool = False,
        reliability_analyzer=None,
    ):
        """Refit ProbabilityCalibrator from settled bets when thresholds are met."""

        result = self.calibration_job.maybe_refit(
            force=force,
            reliability_analyzer=reliability_analyzer,
        )
        self.last_calibration_result = result
        return result

    def recovery_cycle(
        self,
        regime_detector,
        reliability_analyzer=None,
    ):

        calibration_result = self.maybe_recalibrate(
            reliability_analyzer=reliability_analyzer,
        )

        if not self.should_retrain(

            regime_detector
        ):

            return {

                "action":
                    "CALIBRATION_ONLY"
                    if calibration_result.get("status") == "FITTED"
                    else "NONE",

                "calibration":
                    calibration_result,
            }

        print("\n====================")
        print("RECOVERY CYCLE")
        print("====================")

        print(
            "regime:",
            regime_detector
            .current_regime
        )

        result = self.retrain()
        result["calibration"] = calibration_result

        return result

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "last_retrain":
                self.last_retrain,

            "last_result":
                self.last_result,

            "dataset_path":
                self.dataset_path,

            "model_path":
                self.model_path,

            "last_calibration_result":
                self.last_calibration_result,

            "calibration_job":
                self.calibration_job.last_result,
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    retrainer = (
        AutoRetrainer()
    )

    result = (
        retrainer.retrain()
    )

    print("\nRESULT")

    print(result)