# learning/strategy_evolver.py

import os
import json
import random
import joblib
import numpy as np
import pandas as pd

from copy import deepcopy
from datetime import datetime

from sklearn.ensemble import (
    RandomForestClassifier,
    GradientBoostingClassifier,
)

from sklearn.linear_model import (
    LogisticRegression
)

from sklearn.metrics import (
    log_loss,
    accuracy_score,
)

class StrategyEvolver:
    """
    Evolution Layer

    目的:
    - strategy evolution
    - edge discovery
    - adaptive exploration
    - survival mutation

    最重要:
    「新しい優位性を探し続ける」
    """

    def __init__(

        self,

        generations=10,

        population_size=12,

        survival_threshold=0.55,
    ):

        self.generations = (
            generations
        )

        self.population_size = (
            population_size
        )

        self.survival_threshold = (
            survival_threshold
        )

        # =================================================
        # storage
        # =================================================

        self.output_dir = (
            "models/evolution"
        )

        os.makedirs(

            self.output_dir,

            exist_ok=True,
        )

        # =================================================
        # tracking
        # =================================================

        self.history = []

        self.best_candidate = None

        self.best_score = -999999

    # =================================================
    # Candidate Templates
    # =================================================

    def base_candidates(
        self,
    ):

        return [

            {
                "name":
                    "rf_small",

                "model":
                    RandomForestClassifier(

                        n_estimators=50,

                        max_depth=4,

                        random_state=42,
                    ),
            },

            {
                "name":
                    "rf_large",

                "model":
                    RandomForestClassifier(

                        n_estimators=200,

                        max_depth=8,

                        random_state=42,
                    ),
            },

            {
                "name":
                    "gb_small",

                "model":
                    GradientBoostingClassifier(

                        n_estimators=100,

                        learning_rate=0.05,

                        random_state=42,
                    ),
            },

            {
                "name":
                    "logistic",

                "model":
                    LogisticRegression(

                        max_iter=500
                    ),
            },
        ]

    # =================================================
    # Feature Mutation
    # =================================================

    def mutate_features(
        self,
        df,
    ):

        data = df.copy()

        numeric_cols = data.select_dtypes(
            include=np.number
        ).columns.tolist()

        ignored = {

            "target",
            "label",
            "y",
        }

        numeric_cols = [

            c for c in numeric_cols

            if c not in ignored
        ]

        # =================================================
        # random feature engineering
        # =================================================

        if len(numeric_cols) >= 2:

            a, b = random.sample(
                numeric_cols,
                2,
            )

            mode = random.choice([

                "add",
                "sub",
                "mul",
                "div",
            ])

            new_col = (
                f"{a}_{mode}_{b}"
            )

            try:

                if mode == "add":

                    data[new_col] = (
                        data[a] + data[b]
                    )

                elif mode == "sub":

                    data[new_col] = (
                        data[a] - data[b]
                    )

                elif mode == "mul":

                    data[new_col] = (
                        data[a] * data[b]
                    )

                elif mode == "div":

                    data[new_col] = (

                        data[a]
                        / (
                            data[b]
                            + 1e-6
                        )
                    )

            except:
                pass

        return data

    # =================================================
    # Mutation
    # =================================================

    def mutate_model(
        self,
        candidate,
    ):

        c = deepcopy(candidate)

        model = c["model"]

        # =================================================
        # RF mutation
        # =================================================

        if isinstance(

            model,

            RandomForestClassifier,
        ):

            model.n_estimators = random.choice(

                [50, 100, 200, 300]
            )

            model.max_depth = random.choice(

                [3, 4, 6, 8, 12]
            )

        # =================================================
        # GB mutation
        # =================================================

        elif isinstance(

            model,

            GradientBoostingClassifier,
        ):

            model.learning_rate = (
                random.choice(

                    [0.01, 0.03, 0.05, 0.1]
                )
            )

            model.n_estimators = (
                random.choice(

                    [50, 100, 200]
                )
            )

        return c

    # =================================================
    # Evaluation
    # =================================================

    def evaluate(

        self,

        candidate,
        df,
        target_col="target",
    ):

        try:

            data = (
                self.mutate_features(
                    df
                )
            )

            # =================================================
            # target
            # =================================================

            if target_col not in data.columns:

                return None

            y = data[target_col]

            X = data.drop(
                columns=[target_col]
            )

            X = X.select_dtypes(
                include=np.number
            )

            if len(X.columns) == 0:

                return None

            # =================================================
            # split
            # =================================================

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

            model = candidate["model"]

            model.fit(
                X_train,
                y_train,
            )

            # =================================================
            # predict
            # =================================================

            probs = (
                model.predict_proba(
                    X_test
                )[:, 1]
            )

            preds = (
                probs > 0.5
            ).astype(int)

            # =================================================
            # metrics
            # =================================================

            acc = accuracy_score(
                y_test,
                preds,
            )

            loss = log_loss(
                y_test,
                probs,
            )

            # =================================================
            # simulation
            # =================================================

            from simulation.live_simulation import (
                LiveSimulation
            )

            sim_df = pd.DataFrame({

                "prediction":
                    probs,

                "target":
                    y_test.values,
            })

            simulator = (
                LiveSimulation()
            )

            sim = simulator.run(
                sim_df
            )

            survival = sim.get(
                "survival_score",
                0,
            )

            # =================================================
            # combined fitness
            # =================================================

            fitness = (

                survival * 0.6

                + acc * 0.3

                - loss * 0.1
            )

            result = {

                "candidate":
                    candidate["name"],

                "fitness":
                    float(fitness),

                "accuracy":
                    float(acc),

                "log_loss":
                    float(loss),

                "survival":
                    float(survival),

                "features":
                    list(X.columns),
            }

            return result

        except Exception as e:

            print(
                "[EVALUATION ERROR]",
                e,
            )

            return None

    # =================================================
    # Evolution Cycle
    # =================================================

    def evolve(
        self,
        dataset,
    ):

        print("\n====================")
        print("EVOLUTION START")
        print("====================")

        population = (
            self.base_candidates()
        )

        # =================================================
        # fill population
        # =================================================

        while (

            len(population)

            < self.population_size
        ):

            base = random.choice(
                population
            )

            mutated = (
                self.mutate_model(
                    base
                )
            )

            population.append(
                mutated
            )

        # =================================================
        # generations
        # =================================================

        for generation in range(

            self.generations
        ):

            print(
                f"\nGENERATION "
                f"{generation}"
            )

            scored = []

            # =============================================
            # evaluate
            # =============================================

            for candidate in population:

                result = self.evaluate(

                    candidate,

                    dataset,
                )

                if result:

                    scored.append({

                        "candidate":
                            candidate,

                        "result":
                            result,
                    })

                    print(result)

            if len(scored) == 0:

                continue

            # =============================================
            # sort
            # =============================================

            scored = sorted(

                scored,

                key=lambda x:
                    x["result"][
                        "fitness"
                    ],

                reverse=True,
            )

            # =============================================
            # best
            # =============================================

            best = scored[0]

            score = best["result"][
                "fitness"
            ]

            if score > self.best_score:

                self.best_score = score

                self.best_candidate = best

                self.save_candidate(
                    best
                )

            # =============================================
            # history
            # =============================================

            self.history.append({

                "generation":
                    generation,

                "best_score":
                    score,

                "timestamp":
                    datetime.utcnow()
                    .isoformat(),
            })

            # =============================================
            # natural selection
            # =============================================

            survivors = scored[
                : max(
                    2,
                    len(scored) // 2
                )
            ]

            new_population = []

            for s in survivors:

                new_population.append(
                    s["candidate"]
                )

                mutated = (
                    self.mutate_model(
                        s["candidate"]
                    )
                )

                new_population.append(
                    mutated
                )

            population = (
                new_population[
                    : self.population_size
                ]
            )

        print("\n====================")
        print("EVOLUTION COMPLETE")
        print("====================")

        return {

            "best_score":
                self.best_score,

            "best_candidate":
                self.best_candidate,

            "history":
                self.history,
        }

    # =================================================
    # Save Candidate
    # =================================================

    def save_candidate(
        self,
        best,
    ):

        timestamp = datetime.utcnow().strftime(
            "%Y%m%d_%H%M%S"
        )

        model = best[
            "candidate"
        ]["model"]

        path = os.path.join(

            self.output_dir,

            f"evolved_{timestamp}.pkl"
        )

        joblib.dump(
            model,
            path,
        )

        metadata = {

            "timestamp":
                timestamp,

            "score":
                best["result"][
                    "fitness"
                ],

            "metrics":
                best["result"],
        }

        with open(

            path + ".json",

            "w",

            encoding="utf-8",
        ) as f:

            json.dump(

                metadata,

                f,

                indent=2,

                ensure_ascii=False,
            )

        print(
            f"[EVOLVED MODEL SAVED] "
            f"{path}"
        )

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "generations":
                self.generations,

            "population_size":
                self.population_size,

            "best_score":
                self.best_score,

            "history_count":
                len(
                    self.history
                ),

            "best_exists":
                (
                    self.best_candidate
                    is not None
                ),
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    df = pd.DataFrame({

        "speed":
            np.random.randn(1000),

        "odds":
            np.random.randn(1000),

        "power":
            np.random.randn(1000),

        "target":
            np.random.randint(
                0,
                2,
                1000,
            ),
    })

    evolver = (
        StrategyEvolver(

            generations=5,

            population_size=8,
        )
    )

    result = evolver.evolve(
        df
    )

    print(result)

    print(
        evolver.diagnostics()
    )