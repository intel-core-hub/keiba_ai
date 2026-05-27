# learning/meta_learner.py

import os
import json
import numpy as np
import pandas as pd

from datetime import datetime

from sklearn.ensemble import (
    RandomForestRegressor
)

from sklearn.preprocessing import (
    LabelEncoder
)

from sklearn.metrics import (
    mean_absolute_error
)


class MetaLearner:
    """
    Meta Intelligence Layer

    目的:
    - learn adaptation patterns
    - discover survival structures
    - optimize evolution itself
    - reduce useless exploration

    最重要:
    「進化の仕方を学ぶ」
    """

    def __init__(

        self,

        meta_log_path=(
            "logs/meta_learning.jsonl"
        ),
    ):

        self.meta_log_path = (
            meta_log_path
        )

        os.makedirs(
            "logs",
            exist_ok=True,
        )

        # =================================================
        # meta model
        # =================================================

        self.meta_model = (
            RandomForestRegressor(

                n_estimators=200,

                max_depth=6,

                random_state=42,
            )
        )

        self.feature_encoder = (
            LabelEncoder()
        )

        self.model_encoder = (
            LabelEncoder()
        )

        self.trained = False

        self.meta_history = []

    # =================================================
    # Record Evolution Event
    # =================================================

    def record(

        self,

        regime,
        model_type,
        mutation_type,
        fitness,
        survival,
        accuracy,
        metadata=None,
    ):

        event = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "regime":
                regime,

            "model_type":
                model_type,

            "mutation_type":
                mutation_type,

            "fitness":
                float(fitness),

            "survival":
                float(survival),

            "accuracy":
                float(accuracy),

            "metadata":
                metadata or {},
        }

        with open(

            self.meta_log_path,

            "a",

            encoding="utf-8",
        ) as f:

            f.write(

                json.dumps(

                    event,

                    ensure_ascii=False,
                )

                + "\n"
            )

        self.meta_history.append(
            event
        )

        return event

    # =================================================
    # Load History
    # =================================================

    def load_history(
        self,
    ):

        if not os.path.exists(
            self.meta_log_path
        ):

            return []

        history = []

        with open(

            self.meta_log_path,

            "r",

            encoding="utf-8",
        ) as f:

            for line in f:

                try:

                    history.append(
                        json.loads(
                            line
                        )
                    )

                except:
                    pass

        self.meta_history = (
            history
        )

        return history

    # =================================================
    # Build Dataset
    # =================================================

    def build_dataset(
        self,
    ):

        history = (
            self.load_history()
        )

        if len(history) < 20:

            return None

        df = pd.DataFrame(
            history
        )

        # =================================================
        # categorical encoding
        # =================================================

        df["regime_encoded"] = (
            self.feature_encoder
            .fit_transform(
                df["regime"]
            )
        )

        df["model_encoded"] = (
            self.model_encoder
            .fit_transform(
                df["model_type"]
            )
        )

        mutation_map = {

            "feature_add": 1,

            "feature_sub": 2,

            "feature_mul": 3,

            "feature_div": 4,

            "param_mutation": 5,

            "architecture_shift": 6,
        }

        df["mutation_encoded"] = (
            df["mutation_type"]
            .map(
                mutation_map
            )
        )

        df["mutation_encoded"] = (
            df["mutation_encoded"]
            .fillna(0)
        )

        features = [

            "regime_encoded",

            "model_encoded",

            "mutation_encoded",

            "accuracy",

            "survival",
        ]

        X = df[features]

        y = df["fitness"]

        return X, y

    # =================================================
    # Train Meta Model
    # =================================================

    def train(
        self,
    ):

        dataset = (
            self.build_dataset()
        )

        if dataset is None:

            print(
                "[META] "
                "not enough history"
            )

            return None

        X, y = dataset

        split = int(
            len(X) * 0.8
        )

        X_train = X.iloc[:split]
        X_test = X.iloc[split:]

        y_train = y.iloc[:split]
        y_test = y.iloc[split:]

        # =================================================
        # fit
        # =================================================

        self.meta_model.fit(

            X_train,

            y_train,
        )

        # =================================================
        # evaluate
        # =================================================

        preds = (
            self.meta_model.predict(
                X_test
            )
        )

        mae = mean_absolute_error(

            y_test,

            preds,
        )

        self.trained = True

        result = {

            "samples":
                len(X),

            "mae":
                float(mae),

            "trained":
                True,
        }

        print(
            "[META TRAINED]",
            result,
        )

        return result

    # =================================================
    # Predict Mutation Value
    # =================================================

    def predict_success(

        self,

        regime,
        model_type,
        mutation_type,
        accuracy,
        survival,
    ):

        if not self.trained:

            return None

        try:

            regime_encoded = (
                self.feature_encoder
                .transform(
                    [regime]
                )[0]
            )

            model_encoded = (
                self.model_encoder
                .transform(
                    [model_type]
                )[0]
            )

        except:

            return None

        mutation_map = {

            "feature_add": 1,

            "feature_sub": 2,

            "feature_mul": 3,

            "feature_div": 4,

            "param_mutation": 5,

            "architecture_shift": 6,
        }

        mutation_encoded = (
            mutation_map.get(
                mutation_type,
                0,
            )
        )

        X = pd.DataFrame([{

            "regime_encoded":
                regime_encoded,

            "model_encoded":
                model_encoded,

            "mutation_encoded":
                mutation_encoded,

            "accuracy":
                accuracy,

            "survival":
                survival,
        }])

        predicted = (
            self.meta_model.predict(
                X
            )[0]
        )

        return float(predicted)

    # =================================================
    # Recommend Exploration
    # =================================================

    def recommend(
        self,
        regime="NORMAL",
    ):

        if not self.trained:

            return {

                "status":
                    "UNTRAINED"
            }

        candidate_models = [

            "rf_small",

            "rf_large",

            "gb_small",

            "logistic",
        ]

        mutations = [

            "feature_add",

            "feature_sub",

            "feature_mul",

            "feature_div",

            "param_mutation",
        ]

        recommendations = []

        for model in candidate_models:

            for mutation in mutations:

                predicted = (
                    self.predict_success(

                        regime=regime,

                        model_type=model,

                        mutation_type=mutation,

                        accuracy=0.50,

                        survival=0.50,
                    )
                )

                if predicted is None:
                    continue

                recommendations.append({

                    "model":
                        model,

                    "mutation":
                        mutation,

                    "predicted_fitness":
                        predicted,
                })

        recommendations = sorted(

            recommendations,

            key=lambda x:
                x["predicted_fitness"],

            reverse=True,
        )

        return recommendations[:10]

    # =================================================
    # Feature Importance
    # =================================================

    def importance(
        self,
    ):

        if not self.trained:

            return None

        names = [

            "regime",

            "model",

            "mutation",

            "accuracy",

            "survival",
        ]

        importances = (
            self.meta_model
            .feature_importances_
        )

        result = {}

        for name, value in zip(

            names,

            importances,
        ):

            result[name] = float(
                value
            )

        return result

    # =================================================
    # Discover Survival Patterns
    # =================================================

    def discover_patterns(
        self,
    ):

        history = (
            self.load_history()
        )

        if len(history) == 0:

            return None

        df = pd.DataFrame(
            history
        )

        patterns = {}

        # =================================================
        # best regime
        # =================================================

        regime_stats = (

            df.groupby("regime")[
                "fitness"
            ]
            .mean()
            .to_dict()
        )

        patterns[
            "regime_strength"
        ] = regime_stats

        # =================================================
        # best mutation
        # =================================================

        mutation_stats = (

            df.groupby(
                "mutation_type"
            )["fitness"]
            .mean()
            .to_dict()
        )

        patterns[
            "mutation_strength"
        ] = mutation_stats

        # =================================================
        # best model
        # =================================================

        model_stats = (

            df.groupby(
                "model_type"
            )["fitness"]
            .mean()
            .to_dict()
        )

        patterns[
            "model_strength"
        ] = model_stats

        return patterns

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "trained":
                self.trained,

            "history_size":
                len(
                    self.meta_history
                ),

            "importance":
                self.importance(),
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    meta = MetaLearner()

    # =================================================
    # fake history
    # =================================================

    for _ in range(100):

        meta.record(

            regime=np.random.choice([

                "NORMAL",

                "DRIFT",

                "FAVORABLE",
            ]),

            model_type=np.random.choice([

                "rf_small",

                "rf_large",

                "gb_small",
            ]),

            mutation_type=np.random.choice([

                "feature_add",

                "feature_mul",

                "param_mutation",
            ]),

            fitness=np.random.rand(),

            survival=np.random.rand(),

            accuracy=np.random.rand(),
        )

    meta.train()

    print(
        meta.recommend(
            regime="DRIFT"
        )
    )

    print(
        meta.discover_patterns()
    )

    print(
        meta.diagnostics()
    )