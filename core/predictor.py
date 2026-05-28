from core.prediction.predictor import Predictor
# core/predictor.py

import os
import joblib
import numpy as np
import threading
from time import perf_counter
try:
    import pandas as pd
except Exception:
    pd = None

from sklearn.calibration import (
    CalibratedClassifierCV
)

from sklearn.metrics import (
    brier_score_loss,
    log_loss,
)

from sklearn.model_selection import (
    train_test_split,
)

from sklearn.ensemble import (
    RandomForestClassifier
)

from sklearn.impute import (
    SimpleImputer
)

from sklearn.pipeline import Pipeline

from sklearn.preprocessing import (
    StandardScaler,
)

from schemas.race_schema import (
    RaceSchemaUtils
)


class Predictor:
    """
    Survival Predictor

    思想:
    accuracy最大化
    ではない

    calibration維持
    survival維持
    が目的
    """

    def __init__(

        self,

        model_path="models/predictor.pkl",
    ):

        self.model_path = model_path

        self.model = None

        self.feature_names = None

        self.trained = False

        # cached feature metadata for low-latency path
        self._feature_idx = None
        self._n_features = 0

        # thread-local buffers to avoid cross-thread races while reusing arrays
        self._thread_local = threading.local()

        # simple profiling counters for predict_raw
        self._enable_predict_raw_profiling = False
        self._predict_raw_stats = {
            "count": 0,
            "assemble_time": 0.0,
            "predict_time": 0.0,
        }

        # -----------------------------------------
        # calibration targets
        # -----------------------------------------

        self.max_brier = 0.22

        self.max_logloss = 0.68

        # -----------------------------------------
        # training metadata
        # -----------------------------------------

        self.training_rows = 0

        self.last_metrics = {}

        # -----------------------------------------
        # load existing model
        # -----------------------------------------

        self.load()

    # =================================================
    # Build Pipeline
    # =================================================

    def build_pipeline(self, cv=3, calibrated=True):

        """
        生存重視:
        過学習しにくい構成
        """

        base_model = (
            RandomForestClassifier(

                n_estimators=200,

                max_depth=6,

                min_samples_leaf=8,

                random_state=42,

                class_weight="balanced",
            )
        )

        if calibrated:
            model = CalibratedClassifierCV(
                estimator=base_model,
                method="sigmoid",
                cv=cv,
            )
        else:
            model = base_model

        pipeline = Pipeline([

            (
                "imputer",

                SimpleImputer(
                    strategy="median"
                ),
            ),

            (
                "scaler",

                StandardScaler()
            ),

            (
                "model",

                model
            ),
        ])

        return pipeline

    # =================================================
    # Train
    # =================================================

    def train(

        self,

        dataframe,

        target_col="target_win",
    ):

        """
        dataframe:
        historical horse records
        """

        if target_col not in dataframe:

            raise ValueError(
                "target column missing"
            )

        # -----------------------------------------
        # leakage detection
        # -----------------------------------------

        leakage = (
            RaceSchemaUtils
            .detect_leakage(
                dataframe.columns
            )
        )

        allowed_targets = [

            "target_win",

            "target_place",

            "finishing_position",

            "last_finish",

            "avg_finish_last5",

            "avg_speed_index_last5",

            "recent_form_score",
        ]

        dangerous = [

            c for c in leakage

            if c not in allowed_targets
        ]

        if len(dangerous) > 0:

            raise ValueError(

                f"Potential leakage detected: "
                f"{dangerous}"
            )

        # -----------------------------------------
        # remove non-features
        # -----------------------------------------

        excluded = [

            "race_id",

            "horse_id",

            "horse_name",

            "race_date",

            "created_at",

            "target_win",

            "target_place",

            "finishing_position",
        ]

        feature_cols = [

            c for c in dataframe.columns

            if c not in excluded
        ]

        # keep only numeric
        numeric_cols = []

        for c in feature_cols:

            try:

                pd.to_numeric(
                    dataframe[c]
                )

                numeric_cols.append(c)

            except:
                pass

        X = dataframe[
            numeric_cols
        ].copy()

        empty_cols = [
            c for c in X.columns
            if X[c].isna().all()
        ]
        if empty_cols:
            X = X.drop(columns=empty_cols)
            numeric_cols = [c for c in numeric_cols if c not in empty_cols]

        y = dataframe[
            target_col
        ].astype(int)

        self.feature_names = (
            numeric_cols
        )

        # cache feature index mapping and counts for predict_raw
        self._feature_idx = {f: i for i, f in enumerate(self.feature_names)}
        self._n_features = len(self.feature_names)

        # -----------------------------------------
        # split
        # -----------------------------------------

        X_train, X_valid, y_train, y_valid = (
            train_test_split(

                X,
                y,

                test_size=0.2,

                shuffle=False,
            )
        )

        # -----------------------------------------
        # train
        # -----------------------------------------

        self.model = (
            self.build_pipeline()
        )

        self.model.fit(
            X_train,
            y_train,
        )

        # -----------------------------------------
        # validation
        # -----------------------------------------

        probs = (
            self.model
            .predict_proba(X_valid)
        )[:, 1]

        brier = (
            brier_score_loss(
                y_valid,
                probs,
            )
        )

        ll = (
            log_loss(
                y_valid,
                probs,
                labels=[0, 1],
            )
        )

        self.last_metrics = {

            "brier":
                round(brier, 6),

            "logloss":
                round(ll, 6),

            "rows":
                len(dataframe),

            "features":
                len(numeric_cols),
        }

        self.training_rows = (
            len(dataframe)
        )

        self.trained = True

        # -----------------------------------------
        # survival validation
        # -----------------------------------------

        if brier > self.max_brier:

            print(
                "[WARNING] "
                "Poor calibration"
            )

        if ll > self.max_logloss:

            print(
                "[WARNING] "
                "Poor logloss"
            )

        # -----------------------------------------
        # save
        # -----------------------------------------

        self.save()

        return self.last_metrics

    # =================================================
    # Predict
    # =================================================

    def predict(

        self,

        race_id,
        selection,
        features,
        odds=None,
    ):

        """
        単一馬予測

        NOTE:
        未学習時は
        fallback heuristic
        """

        # =================================================
        # fallback
        # =================================================

        if (

            not self.trained

            or self.model is None

        ):

            return self.fallback_predict(
                features,
                odds,
            )

        # =================================================
        # dataframe
        # =================================================

        row = {}

        for f in self.feature_names:

            row[f] = features.get(
                f,
                np.nan,
            )

        X = pd.DataFrame([row])

        # =================================================
        # predict
        # =================================================

        try:

            prob = (
                self.model
                .predict_proba(X)
            )[0][1]

            # -----------------------------------------
            # safety clipping
            # -----------------------------------------

            prob = np.clip(
                prob,
                0.01,
                0.99,
            )

            return float(prob)

        except Exception as e:

            print(
                "[PREDICT ERROR]",
                e,
            )

            return self.fallback_predict(
                features,
                odds,
            )

    def predict_raw(self, features: dict, odds=None) -> float:
        """
        Low-latency prediction path that avoids pandas and uses numpy arrays
        so it can be executed in a threadpool without incurring DataFrame
        allocation overhead on the critical path.
        """
        if (not self.trained) or (self.model is None):
            return self.fallback_predict(features, odds)

        # Prepare thread-local fixed-size buffer to avoid repeated allocations
        n = self._n_features or len(self.feature_names or [])
        if n == 0:
            return self.fallback_predict(features, odds)

        tl = self._thread_local
        buf = getattr(tl, "predict_buf", None)
        if buf is None or buf.size != n:
            buf = np.empty(n, dtype=float)
            tl.predict_buf = buf

        start_assemble = perf_counter()
        # fill buffer in-order
        for i, f in enumerate(self.feature_names):
            v = features.get(f, None)
            if v is None:
                buf[i] = np.nan
            else:
                try:
                    buf[i] = float(v)
                except Exception:
                    buf[i] = np.nan
        assemble_time = perf_counter() - start_assemble

        X = buf.reshape(1, -1)

        try:
            start_pred = perf_counter()
            prob = self.model.predict_proba(X)[0][1]
            predict_time = perf_counter() - start_pred

            # update lightweight profiling
            if self._enable_predict_raw_profiling:
                s = self._predict_raw_stats
                s["count"] += 1
                s["assemble_time"] += assemble_time
                s["predict_time"] += predict_time

            prob = np.clip(prob, 0.01, 0.99)
            return float(prob)
        except Exception:
            return self.fallback_predict(features, odds)

    # =================================================
    # Fallback Predictor
    # =================================================

    def fallback_predict(
        self,
        features,
        odds,
    ):

        """
        survival fallback

        予測不能でも
        暴走しない
        """

        score = np.mean([

            features.get(
                "rank_score",
                0.5,
            ),

            features.get(
                "recent_form_score",
                0.5,
            ),

            features.get(
                "market_support",
                0.5,
            ),

            features.get(
                "consistency_index",
                0.5,
            ),
        ])

        # market anchor
        if odds:

            market_prob = (
                1 / odds
            )

            score = (

                score * 0.6

                + market_prob * 0.4
            )

        return float(np.clip(
            score,
            0.02,
            0.95,
        ))

    # =================================================
    # Feature Importance
    # =================================================

    def feature_importance(
        self,
    ):

        if not self.trained:

            return {}

        try:

            calibrated = (
                self.model
                .named_steps["model"]
            )

            forest = (
                calibrated
                .estimator
            )

            importance = (
                forest
                .feature_importances_
            )

            pairs = list(zip(

                self.feature_names,

                importance,
            ))

            pairs = sorted(

                pairs,

                key=lambda x: x[1],

                reverse=True,
            )

            return {

                k: round(v, 6)

                for k, v in pairs
            }

        except:
            return {}

    # =================================================
    # Save
    # =================================================

    def save(
        self,
    ):

        if self.model is None:
            return

        os.makedirs(
            "models",
            exist_ok=True,
        )

        payload = {

            "model":
                self.model,

            "feature_names":
                self.feature_names,

            "trained":
                self.trained,

            "training_rows":
                self.training_rows,

            "metrics":
                self.last_metrics,
        }

        joblib.dump(
            payload,
            self.model_path,
        )

    # =================================================
    # Load
    # =================================================

    def load(
        self,
    ):

        if not os.path.exists(
            self.model_path
        ):

            return False

        try:

            payload = joblib.load(
                self.model_path
            )

            self.model = payload[
                "model"
            ]

            self.feature_names = payload[
                "feature_names"
            ]

            self.trained = payload[
                "trained"
            ]

            self.training_rows = payload.get(
                "training_rows",
                0,
            )

            self.last_metrics = payload.get(
                "metrics",
                {},
            )
            # ensure cached metadata exists after loading
            try:
                self._feature_idx = {f: i for i, f in enumerate(self.feature_names)}
                self._n_features = len(self.feature_names)
            except Exception:
                self._feature_idx = None
                self._n_features = 0

            return True

        except Exception as e:

            print(
                "[LOAD ERROR]",
                e,
            )

            return False

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "trained":
                self.trained,

            "training_rows":
                self.training_rows,

            "features":
                len(
                    self.feature_names
                    or []
                ),

            "metrics":
                self.last_metrics,
        }

    def enable_predict_raw_profiling(self, enable: bool = True):
        """Enable/disable lightweight profiling for `predict_raw`."""
        self._enable_predict_raw_profiling = bool(enable)

    def get_predict_raw_stats(self):
        """Return aggregated predict_raw profiling stats."""
        return dict(self._predict_raw_stats)


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    predictor = Predictor()

    # -----------------------------------------
    # fallback example
    # -----------------------------------------

    features = {

        "rank_score": 0.82,

        "recent_form_score": 0.75,

        "market_support": 0.71,

        "consistency_index": 0.80,
    }

    prob = predictor.predict(

        race_id="TEST",

        selection="Horse_A",

        features=features,

        odds=4.5,
    )

    print(
        "\nProbability:",
        round(prob, 4)
    )

    print(
        predictor.diagnostics()
    )