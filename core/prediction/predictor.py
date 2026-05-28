# core/predictor.py

import os
import joblib
import numpy as np
import time
import json
from collections import OrderedDict

from sklearn.metrics import (
    brier_score_loss,
    log_loss,
)

from sklearn.model_selection import (
    train_test_split,
)

from schemas.race_schema import (
    RaceSchemaUtils
)

from learning.model_factory import build_boosted_pipeline


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

        # in-memory predict cache: OrderedDict for simple LRU
        # key -> (timestamp, value)
        self._predict_cache = OrderedDict()
        self._predict_cache_ttl = float(os.getenv("PREDICT_CACHE_TTL", "10"))
        self._predict_cache_max = int(os.getenv("PREDICT_CACHE_MAX", "1024"))

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
        return build_boosted_pipeline(
            cv=cv,
            calibrated=calibrated,
            use_scaler=False,
        )

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

        import pandas as pd

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

        class_counts = y_train.value_counts()
        min_class_count = int(class_counts.min()) if not class_counts.empty else 0

        if min_class_count >= 2:
            self.model = self.build_pipeline(cv=min(3, min_class_count), calibrated=True)
        else:
            print("[WARNING] small class count; using uncalibrated model")
            self.model = self.build_pipeline(calibrated=False)

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

    def fit(self, X, y):
        df = pd.DataFrame(X).copy()
        df.columns = [f"f{i}" for i in range(df.shape[1])]
        if "target_win" in df.columns:
            df = df.drop(columns=["target_win"])
        df["target_win"] = np.asarray(y).astype(int)
        return self.train(df, target_col="target_win")

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
        # caching
        # =================================================
        try:
            model_version = None
            try:
                if isinstance(self.model_path, str) and os.path.exists(self.model_path):
                    model_version = os.path.getmtime(self.model_path)
            except Exception:
                model_version = id(self.model)

            features_serial = json.dumps(features or {}, sort_keys=True, separators=(",", ":"), default=str)
            cache_key = f"{race_id}|{selection}|{features_serial}|{model_version}"

            # prune expired entries
            now = time.time()
            to_delete = []
            for k, (ts, _) in list(self._predict_cache.items()):
                if now - ts > self._predict_cache_ttl:
                    to_delete.append(k)
            for k in to_delete:
                self._predict_cache.pop(k, None)

            # try cache hit
            cached = self._predict_cache.get(cache_key)
            if cached is not None:
                # move to end (LRU)
                ts, val = self._predict_cache.pop(cache_key)
                self._predict_cache[cache_key] = (ts, val)
                return float(val)
        except Exception:
            # caching must not break prediction
            pass

        # =================================================
        # fallback (untrained)
        # =================================================
        if (not self.trained or self.model is None):
            val = self.fallback_predict(features, odds)
            try:
                # store in cache
                self._predict_cache[cache_key] = (time.time(), float(val))
                # enforce max size
                while len(self._predict_cache) > self._predict_cache_max:
                    self._predict_cache.popitem(last=False)
            except Exception:
                pass
            return val

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

            result = float(prob)
            try:
                self._predict_cache[cache_key] = (time.time(), result)
                while len(self._predict_cache) > self._predict_cache_max:
                    self._predict_cache.popitem(last=False)
            except Exception:
                pass
            return result

        except Exception as e:

            print(
                "[PREDICT ERROR]",
                e,
            )

            return self.fallback_predict(
                features,
                odds,
            )

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