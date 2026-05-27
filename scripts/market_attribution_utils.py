from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

from learning.model_factory import build_boosted_pipeline, build_logistic_pipeline
from learning.uncertainty import estimate_uncertainty


warnings.filterwarnings("ignore", message="X does not have valid feature names*")


PREDICTOR_FEATURES: list[str] = [
    "odds",
    "favorite_rank",
    "weight_carried",
    "age",
    "horse_weight",
    "horse_weight_diff",
    "avg_finish_last5",
    "avg_finish_last3",
    "avg_speed_index_last5",
    "recent_form_score",
    "last_finish",
    "rest_days",
]

IDENTIFIER_COLUMNS: set[str] = {
    "race_id",
    "horse_id",
    "horse_name",
    "jockey",
    "trainer",
    "scraped_at",
    "created_at",
    "source_file",
    "race_date",
}

TARGET_COLUMNS: set[str] = {
    "target_win",
    "target_place",
    "finishing_position",
    "hit",
    "actual_pos",
}

EARLY_ODDS_CANDIDATES: list[str] = [
    "odds_t60",
    "odds_60m",
    "odds_60min",
    "odds_t30",
    "odds_30m",
    "odds_30min",
    "opening_odds",
    "early_odds",
]

CLOSING_ODDS_CANDIDATES: list[str] = [
    "closing_odds",
    "final_odds",
    "closing_price",
    "market_odds",
]

MARKET_ONLY_CANDIDATES: list[str] = [
    "odds",
    "favorite_rank",
    "odds_value",
    "market_support",
    "public_confidence",
]


@dataclass
class VariantEvaluation:
    name: str
    feature_columns: list[str]
    metrics: dict[str, float]
    predictions: pd.DataFrame | None = None
    available: bool = True
    reason: str | None = None


def load_dataset(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    sort_cols: list[str] = []
    if "race_date" in df.columns:
        sort_cols.append("race_date")
    if "race_id" in df.columns:
        sort_cols.append("race_id")
    if sort_cols:
        df = df.sort_values(sort_cols).reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)
    return df


def resolve_existing_columns(df: pd.DataFrame, candidates: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    resolved: list[str] = []
    for column in candidates:
        if column in df.columns and column not in seen:
            resolved.append(column)
            seen.add(column)
    return resolved


def target_series(df: pd.DataFrame) -> pd.Series:
    if "target_win" in df.columns:
        return pd.to_numeric(df["target_win"], errors="coerce").fillna(0).astype(int)
    if "hit" in df.columns:
        return pd.to_numeric(df["hit"], errors="coerce").fillna(0).astype(int)
    if "finishing_position" in df.columns:
        return (pd.to_numeric(df["finishing_position"], errors="coerce") == 1).astype(int)
    if "actual_pos" in df.columns:
        return (pd.to_numeric(df["actual_pos"], errors="coerce") == 1).astype(int)
    raise ValueError("target column not found")


def market_probability_from_odds(odds: pd.Series | np.ndarray | list[float]) -> pd.Series:
    series = pd.to_numeric(pd.Series(odds), errors="coerce")
    return pd.Series(np.where(series > 0, 1.0 / series, np.nan), index=series.index)


def add_market_columns(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "odds" in work.columns:
        work["odds"] = pd.to_numeric(work["odds"], errors="coerce")
        work["market_probability"] = market_probability_from_odds(work["odds"])
    else:
        work["market_probability"] = np.nan

    if "odds" in work.columns and "target_win" in work.columns:
        work["calibration_gap"] = (pd.to_numeric(work["odds"], errors="coerce") > 0)
        work["calibration_gap"] = np.where(
            work["calibration_gap"],
            np.abs(pd.to_numeric(work.get("pred_prob", pd.Series(np.nan, index=work.index)), errors="coerce") - work["market_probability"]),
            np.nan,
        )
    return work


def split_group_key(df: pd.DataFrame) -> pd.Series:
    if "race_id" in df.columns:
        return df["race_id"].astype(str)
    if "race_date" in df.columns:
        return df["race_date"].astype(str)
    return df.index.astype(str)


def temporal_splits(df: pd.DataFrame, train_ratio: float = 0.7, folds: int = 3) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    if len(df) < 8:
        return []

    ordered = df.copy()
    sort_cols: list[str] = []
    if "race_date" in ordered.columns:
        sort_cols.append("race_date")
    if "race_id" in ordered.columns:
        sort_cols.append("race_id")
    if sort_cols:
        ordered = ordered.sort_values(sort_cols).reset_index(drop=True)
    else:
        ordered = ordered.reset_index(drop=True)

    keys = split_group_key(ordered).drop_duplicates().tolist()
    if len(keys) < 4:
        split_idx = max(1, int(len(ordered) * train_ratio))
        return [(ordered.iloc[:split_idx].copy(), ordered.iloc[split_idx:].copy())]

    initial_train = max(1, int(len(keys) * train_ratio))
    initial_train = min(initial_train, len(keys) - 1)
    remaining = len(keys) - initial_train
    window = max(1, remaining // max(1, folds))

    splits: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    for fold_idx in range(max(1, folds)):
        train_end = min(len(keys) - 1, initial_train + fold_idx * window)
        test_end = min(len(keys), train_end + window)
        if train_end <= 0 or test_end <= train_end:
            break

        train_keys = set(keys[:train_end])
        test_keys = set(keys[train_end:test_end])
        train_df = ordered[split_group_key(ordered).isin(train_keys)].copy()
        test_df = ordered[split_group_key(ordered).isin(test_keys)].copy()
        if len(train_df) == 0 or len(test_df) == 0:
            continue
        splits.append((train_df, test_df))

    if not splits:
        split_idx = max(1, int(len(ordered) * train_ratio))
        splits.append((ordered.iloc[:split_idx].copy(), ordered.iloc[split_idx:].copy()))

    return splits


def race_class_from_title(title: str) -> str:
    text = str(title)
    rules = [
        ("障害", "JUMP"),
        ("G1", "GRADE_1"),
        ("Ｇ１", "GRADE_1"),
        ("G2", "GRADE_2"),
        ("Ｇ２", "GRADE_2"),
        ("G3", "GRADE_3"),
        ("Ｇ３", "GRADE_3"),
        ("オープン", "OPEN"),
        ("OP", "OPEN"),
        ("3勝クラス", "CLASS_3W"),
        ("2勝クラス", "CLASS_2W"),
        ("1勝クラス", "CLASS_1W"),
        ("新馬", "DEBUT"),
        ("未勝利", "MAIDEN"),
        ("特別", "SPECIAL"),
        ("ステークス", "OPEN"),
        ("記念", "OPEN"),
        ("杯", "OPEN"),
        ("賞", "SPECIAL"),
        ("重賞", "STAKES"),
    ]
    for keyword, label in rules:
        if keyword in text:
            return label
    if any(token in text for token in ["3歳", "4歳", "5歳", "6歳"]):
        return "OPEN_AGE"
    return "OTHER"


def odds_regime(odds: float | int | None) -> str:
    value = pd.to_numeric(pd.Series([odds]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "UNKNOWN"
    if value <= 2.0:
        return "FAVORITE_HEAVY"
    if value <= 4.0:
        return "FAVORITE_TO_BALANCED"
    if value <= 8.0:
        return "BALANCED"
    if value <= 20.0:
        return "LONGSHOT"
    return "DEEP_LONGSHOT"


def add_regime_labels(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "odds" in work.columns:
        work["odds_regime"] = work["odds"].apply(odds_regime)
    else:
        work["odds_regime"] = "UNKNOWN"
    if "race_title" in work.columns:
        work["race_class"] = work["race_title"].astype(str).apply(race_class_from_title)
    else:
        work["race_class"] = "UNKNOWN"
    return work


def feature_columns_for_variant(df: pd.DataFrame, variant: str) -> list[str]:
    if variant == "full":
        return [column for column in PREDICTOR_FEATURES if column in df.columns]

    if variant == "no_odds":
        return [column for column in PREDICTOR_FEATURES if column != "odds" and column in df.columns]

    if variant == "market_only":
        return resolve_existing_columns(df, MARKET_ONLY_CANDIDATES + CLOSING_ODDS_CANDIDATES + EARLY_ODDS_CANDIDATES)

    if variant == "early_odds_only":
        return resolve_existing_columns(df, EARLY_ODDS_CANDIDATES)

    if variant == "closing_odds":
        return resolve_existing_columns(df, CLOSING_ODDS_CANDIDATES)

    if variant == "closing_odds_only":
        return resolve_existing_columns(df, CLOSING_ODDS_CANDIDATES)

    raise ValueError(f"unknown variant: {variant}")


def numeric_feature_frame(df: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    frame = df.copy()
    for column in feature_columns:
        if column not in frame.columns:
            frame[column] = 0.0
    X = frame[feature_columns].copy()
    for column in feature_columns:
        X[column] = pd.to_numeric(X[column], errors="coerce").fillna(0.0)
    return X


def build_model(model_kind: str = "boosted", cv: int = 3, calibrated: bool = True):
    if model_kind == "logistic":
        return build_logistic_pipeline(cv=cv, calibrated=calibrated)
    return build_boosted_pipeline(cv=cv, calibrated=calibrated, use_scaler=False)


def _uncertainty_score(probability: float) -> float:
    return float(estimate_uncertainty(float(probability), None)["uncertainty_score"])


def calibration_error(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    return round(float(abs(np.mean(y_prob) - np.mean(y_true))), 6)


def expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, bins: int = 10) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(y_true)
    ece = 0.0
    for start, end in zip(edges[:-1], edges[1:]):
        if end == 1.0:
            mask = (y_prob >= start) & (y_prob <= end)
        else:
            mask = (y_prob >= start) & (y_prob < end)
        count = int(mask.sum())
        if count == 0:
            continue
        avg_prob = float(y_prob[mask].mean())
        avg_hit = float(y_true[mask].mean())
        ece += (count / total) * abs(avg_prob - avg_hit)
    return round(float(ece), 6)


def evaluate_predictions(df: pd.DataFrame, prob_col: str = "pred_prob", uncertainty_threshold: float = 0.65) -> dict[str, float]:
    work = df.copy()
    y = target_series(work).to_numpy(dtype=int)
    probs = pd.to_numeric(work[prob_col], errors="coerce").to_numpy(dtype=float)

    valid_mask = np.isfinite(probs)
    if valid_mask.sum() == 0:
        raise ValueError("no valid probabilities")

    y_valid = y[valid_mask]
    p_valid = np.clip(probs[valid_mask], 1e-6, 1 - 1e-6)

    market_prob = np.full(len(work), np.nan)
    if "odds" in work.columns:
        market_prob = market_probability_from_odds(work["odds"]).to_numpy(dtype=float)

    uncertainty_scores = np.asarray([_uncertainty_score(p) for p in p_valid], dtype=float)
    if len(uncertainty_scores) == 0:
        uncertainty_scores = np.array([0.0])

    result = {
        "rows": float(len(work)),
        "valid_rows": float(len(p_valid)),
        "brier": round(float(brier_score_loss(y_valid, p_valid)), 6),
        "log_loss": round(float(log_loss(y_valid, p_valid, labels=[0, 1])), 6),
        "calibration_gap": calibration_error(y_valid, p_valid),
        "ece": expected_calibration_error(y_valid, p_valid, bins=10),
        "uncertainty_mean": round(float(np.mean(uncertainty_scores)), 6),
        "uncertainty_high_rate": round(float((uncertainty_scores > uncertainty_threshold).mean()), 6),
    }

    if np.isfinite(market_prob[valid_mask]).sum() > 3:
        market_valid = market_prob[valid_mask]
        valid_market_mask = np.isfinite(market_valid)
        if valid_market_mask.sum() > 3:
            pv = p_valid[valid_market_mask]
            mv = market_valid[valid_market_mask]
            result["market_corr"] = round(float(pd.Series(pv).corr(pd.Series(mv))), 6)
            result["market_mae"] = round(float(np.mean(np.abs(pv - mv))), 6)
            result["market_rmse"] = round(float(np.sqrt(np.mean((pv - mv) ** 2))), 6)
        else:
            result["market_corr"] = float("nan")
            result["market_mae"] = float("nan")
            result["market_rmse"] = float("nan")
    else:
        result["market_corr"] = float("nan")
        result["market_mae"] = float("nan")
        result["market_rmse"] = float("nan")

    if "odds" in work.columns:
        odds = pd.to_numeric(work["odds"], errors="coerce").to_numpy(dtype=float)
        expected_value = p_valid * np.where(np.isfinite(odds[valid_mask]), odds[valid_mask], np.nan)
        realized_profit = np.where(y_valid == 1, np.nan_to_num(odds[valid_mask], nan=1.0) - 1.0, -1.0)
        result["edge_mae"] = round(float(np.nanmean(np.abs((expected_value - 1.0) - realized_profit))), 6)
        result["expected_profit_mean"] = round(float(np.nanmean(expected_value - 1.0)), 6)
        result["realized_profit_mean"] = round(float(np.nanmean(realized_profit)), 6)
    else:
        result["edge_mae"] = float("nan")
        result["expected_profit_mean"] = float("nan")
        result["realized_profit_mean"] = float("nan")

    if "race_id" in work.columns and "odds" in work.columns:
        ranked = work.loc[valid_mask].copy()
        ranked[prob_col] = p_valid
        race_pnl = []
        race_hits = []
        for _, group in ranked.groupby("race_id"):
            group = group.dropna(subset=["odds"])
            if group.empty:
                continue
            top = group.loc[group[prob_col].idxmax()]
            odds_value = float(pd.to_numeric(top.get("odds"), errors="coerce") or 0.0)
            hit = int(target_series(pd.DataFrame([top])).iloc[0])
            race_pnl.append((odds_value - 1.0) if hit == 1 else -1.0)
            race_hits.append(hit)
        if race_pnl:
            result["roi_top1"] = round(float((np.sum(race_pnl) / len(race_pnl) + 1.0) * 100.0), 6)
            result["top1_hit_rate"] = round(float(np.mean(race_hits) * 100.0), 6)
            result["top1_pnl"] = round(float(np.sum(race_pnl)), 6)
            result["top1_bets"] = float(len(race_pnl))
        else:
            result["roi_top1"] = float("nan")
            result["top1_hit_rate"] = float("nan")
            result["top1_pnl"] = float("nan")
            result["top1_bets"] = 0.0
    else:
        result["roi_top1"] = float("nan")
        result["top1_hit_rate"] = float("nan")
        result["top1_pnl"] = float("nan")
        result["top1_bets"] = 0.0

    return result


def select_top1_bets(df: pd.DataFrame, prob_col: str = "pred_prob") -> pd.DataFrame:
    if "race_id" not in df.columns or "odds" not in df.columns:
        return pd.DataFrame()

    selected_rows = []
    work = df.copy()
    work[prob_col] = pd.to_numeric(work[prob_col], errors="coerce")
    work["odds"] = pd.to_numeric(work["odds"], errors="coerce")

    for race_id, group in work.groupby("race_id"):
        group = group.dropna(subset=[prob_col, "odds"])
        if group.empty:
            continue
        top = group.loc[group[prob_col].idxmax()].copy()
        actual_win = target_series(pd.DataFrame([top])).iloc[0]
        odds_value = float(top.get("odds", np.nan)) if pd.notna(top.get("odds", np.nan)) else np.nan
        selected_rows.append({
            "race_id": race_id,
            "horse_name": top.get("horse_name", ""),
            "race_title": top.get("race_title", ""),
            "odds": odds_value,
            "pred_prob": float(top.get(prob_col, np.nan)),
            "market_probability": float(top.get("market_probability", np.nan)) if pd.notna(top.get("market_probability", np.nan)) else np.nan,
            "calibration_gap": float(abs(float(top.get(prob_col, np.nan)) - float(top.get("market_probability", np.nan)))) if pd.notna(top.get("market_probability", np.nan)) else np.nan,
            "hit": int(actual_win),
            "expected_value": float(top.get("expected_value", np.nan)) if pd.notna(top.get("expected_value", np.nan)) else np.nan,
            "realized_profit": (odds_value - 1.0) if actual_win == 1 and pd.notna(odds_value) else -1.0,
            "expected_profit": float(top.get("expected_value", np.nan) - 1.0) if pd.notna(top.get("expected_value", np.nan)) else np.nan,
            "odds_regime": top.get("odds_regime", odds_regime(odds_value)),
            "race_class": top.get("race_class", race_class_from_title(top.get("race_title", ""))),
        })

    if not selected_rows:
        return pd.DataFrame()

    return pd.DataFrame(selected_rows)


def fit_predict_variant(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_columns: list[str],
    model_kind: str = "boosted",
) -> tuple[pd.DataFrame | None, dict[str, float], list[str]]:
    feat_cols = [column for column in feature_columns if column in train_df.columns or column in test_df.columns]
    if not feat_cols:
        return None, {"available": 0.0}, []

    X_train = numeric_feature_frame(train_df, feat_cols)
    X_test = numeric_feature_frame(test_df, feat_cols)
    y_train = target_series(train_df)
    y_test = target_series(test_df)

    class_counts = y_train.value_counts()
    min_class_count = int(class_counts.min()) if not class_counts.empty else 0
    calibrated = min_class_count >= 2 and len(X_train) >= 6
    cv_folds = max(2, min(3, min_class_count)) if calibrated else 2

    model = build_model(model_kind=model_kind, cv=cv_folds, calibrated=calibrated)
    model.fit(X_train, y_train)

    try:
        proba = model.predict_proba(X_test)[:, 1]
    except Exception:
        proba = np.full(len(X_test), float(np.mean(y_train) if len(y_train) else 0.5))

    pred_df = test_df.copy()
    pred_df["pred_prob"] = np.round(proba, 6)
    pred_df["market_probability"] = market_probability_from_odds(pred_df["odds"]) if "odds" in pred_df.columns else np.nan
    pred_df["uncertainty_score"] = [
        _uncertainty_score(float(p)) for p in proba
    ]
    pred_df["expected_value"] = np.where(
        "odds" in pred_df.columns,
        np.round(pred_df["pred_prob"] * pd.to_numeric(pred_df["odds"], errors="coerce"), 6),
        np.nan,
    )
    metrics = evaluate_predictions(pred_df)
    metrics["feature_count"] = float(len(feat_cols))
    metrics["calibrated"] = float(calibrated)
    return pred_df, metrics, feat_cols


def summarize_variants(results: list[VariantEvaluation]) -> pd.DataFrame:
    rows = []
    for result in results:
        row = {"variant": result.name, "available": result.available, "reason": result.reason or ""}
        row.update(result.metrics)
        row["features"] = ",".join(result.feature_columns)
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def market_copy_score(full_metrics: dict[str, float], no_odds_metrics: dict[str, float], market_metrics: dict[str, float]) -> dict[str, float]:
    corr = full_metrics.get("market_corr", float("nan"))
    mae = full_metrics.get("market_mae", float("nan"))
    roi_full = full_metrics.get("roi_top1", float("nan"))
    roi_no_odds = no_odds_metrics.get("roi_top1", float("nan"))
    roi_market = market_metrics.get("roi_top1", float("nan"))
    brier_full = full_metrics.get("brier", float("nan"))
    brier_no_odds = no_odds_metrics.get("brier", float("nan"))
    brier_market = market_metrics.get("brier", float("nan"))

    corr_component = 0.5 if pd.isna(corr) else float(np.clip((corr + 1.0) / 2.0, 0.0, 1.0))
    gap_component = 0.5 if pd.isna(mae) else float(np.clip(1.0 - (mae / 0.20), 0.0, 1.0))

    roi_den = abs(roi_market - roi_no_odds) if pd.notna(roi_market) and pd.notna(roi_no_odds) else np.nan
    roi_dependence = 0.5 if pd.isna(roi_den) or roi_den == 0 else float(np.clip((roi_full - roi_no_odds) / roi_den, 0.0, 1.0))

    brier_den = abs(brier_market - brier_no_odds) if pd.notna(brier_market) and pd.notna(brier_no_odds) else np.nan
    brier_dependence = 0.5 if pd.isna(brier_den) or brier_den == 0 else float(np.clip((brier_no_odds - brier_full) / brier_den, 0.0, 1.0))

    score = float(np.clip((corr_component + gap_component + roi_dependence + brier_dependence) / 4.0, 0.0, 1.0))
    return {
        "market_copy_score": round(score * 100.0, 2),
        "corr_component": round(corr_component, 6),
        "gap_component": round(gap_component, 6),
        "roi_dependence_component": round(roi_dependence, 6),
        "brier_dependence_component": round(brier_dependence, 6),
    }
