from __future__ import annotations

try:
    from lightgbm import LGBMClassifier
    _HAS_LIGHTGBM = True
except Exception:
    from sklearn.ensemble import RandomForestClassifier
    _HAS_LIGHTGBM = False

from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def _build_base_boosted_model(random_state: int = 42):
    if _HAS_LIGHTGBM:
        return LGBMClassifier(
            n_estimators=500,
            learning_rate=0.03,
            num_leaves=31,
            max_depth=-1,
            min_child_samples=1,
            min_data_in_leaf=1,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=0.1,
            random_state=random_state,
            class_weight="balanced",
            n_jobs=-1,
            verbosity=-1,
        )

    return RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=8,
        random_state=random_state,
        class_weight="balanced",
    )


def build_boosted_pipeline(
    cv: int = 3,
    calibrated: bool = True,
    use_scaler: bool = False,
    random_state: int = 42,
) -> Pipeline:
    steps = [
        ("imputer", SimpleImputer(strategy="median")),
    ]

    if use_scaler:
        steps.append(("scaler", StandardScaler()))

    base_model = _build_base_boosted_model(random_state=random_state)

    if calibrated:
        model = CalibratedClassifierCV(
            estimator=base_model,
            method="sigmoid",
            cv=cv,
        )
    else:
        model = base_model

    steps.append(("model", model))
    return Pipeline(steps)


def build_logistic_pipeline(
    cv: int = 3,
    calibrated: bool = True,
    random_state: int = 42,
) -> Pipeline:
    steps = [
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ]

    base_model = LogisticRegression(
        C=0.1,
        max_iter=5000,
        class_weight="balanced",
        random_state=random_state,
    )

    if calibrated:
        model = CalibratedClassifierCV(
            estimator=base_model,
            method="sigmoid",
            cv=cv,
        )
    else:
        model = base_model

    steps.append(("model", model))
    return Pipeline(steps)