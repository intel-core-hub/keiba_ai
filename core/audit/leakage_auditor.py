import json
import logging
from typing import List, Optional, Dict, Any, Tuple

import numpy as np
import pandas as pd

from .odds_timestamp_validator import OddsTimestampValidator

logger = logging.getLogger(__name__)


class LeakageAuditor:
    """Performs deterministic, data-driven leakage checks on a dataset.

    Checks implemented:
    - temporal checks (odds timestamp validator)
    - fit timing verification (train/test timestamp ordering per fold)
    - aggregation contamination detection (features equal to full-group aggregates)
    - preprocessing check (numeric train stats vs val stats consistency)
    - replay-style prior-only recomputation for simple group aggregates
    """

    def __init__(
        self,
        df: pd.DataFrame,
        timestamp_col: str = "timestamp",
        id_cols: Optional[List[str]] = None,
        fold_col: Optional[str] = None,
        target_col: Optional[str] = None,
    ) -> None:
        self.df = df.copy()
        self.timestamp_col = timestamp_col
        self.fold_col = fold_col
        self.target_col = target_col
        if id_cols is None:
            # common id candidates
            possible = [c for c in ["horse_id", "race_id", "trainer_id", "jockey_id"] if c in df.columns]
            self.id_cols = possible[:2] if possible else []
        else:
            self.id_cols = id_cols

    def temporal_checks(self) -> Dict[str, Any]:
        report = {}
        # Odds timestamp validator if odds-like columns present
        try:
            validator = OddsTimestampValidator()
            vt = validator.validate(self.df, bet_time_col=self.timestamp_col)
            report["odds_timestamp_validator"] = vt
        except Exception as e:
            report["odds_timestamp_validator_error"] = str(e)
        return report

    def fit_timing_verification(self) -> Dict[str, Any]:
        report: Dict[str, Any] = {"issues": []}
        if self.fold_col is None:
            # try to infer common fold column names
            for cand in ["fold", "cv_fold", "split", "dataset_split"]:
                if cand in self.df.columns:
                    self.fold_col = cand
                    break

        if self.fold_col is None:
            report["error"] = "no fold column found; cannot deterministically verify fold timing"
            return report

        df = self.df
        folds = df[self.fold_col].unique()
        violations = []
        for f in folds:
            val_mask = df[self.fold_col] == f
            train_mask = ~val_mask
            if train_mask.sum() == 0 or val_mask.sum() == 0:
                continue
            train_max = df.loc[train_mask, self.timestamp_col].max()
            val_min = df.loc[val_mask, self.timestamp_col].min()
            if pd.isna(train_max) or pd.isna(val_min):
                violations.append({"fold": f, "reason": "missing timestamps"})
                continue
            if train_max >= val_min:
                violations.append(
                    {"fold": int(f) if isinstance(f, (int, np.integer)) else f, "train_max": str(train_max), "val_min": str(val_min)}
                )

        report["violations"] = violations
        report["status"] = "pass" if not violations else "fail"
        return report

    def aggregation_contamination_check(self) -> Dict[str, Any]:
        df = self.df
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        # exclude common control columns
        exclude = set([self.timestamp_col, self.fold_col, self.target_col])
        exclude = {c for c in exclude if c in df.columns}
        candidate_cols = [c for c in numeric_cols if c not in exclude and not c.lower().startswith("pred_")]

        groups = [c for c in ["horse_id", "trainer_id", "jockey_id", "race_id"] if c in df.columns]
        if not groups:
            return {"error": "no grouping id columns found; cannot run aggregation contamination checks"}

        results = []
        group_key = groups[0]
        g = df.groupby(group_key)
        for col in candidate_cols:
            # compute per-row full-group mean (uses future)
            try:
                full_mean = g[col].transform("mean")
            except Exception:
                continue
            # compute prior-only expanding.shift mean
            prior_mean = g[col].apply(lambda s: s.expanding().mean().shift(1)).reset_index(level=0, drop=True)
            # compare stored col to full_mean and prior_mean
            eq_full = (df[col].fillna(0) == full_mean.fillna(0))
            eq_prior = (df[col].fillna(0) == prior_mean.fillna(0))
            # count rows where stored == full but != prior -> indicates feature equals aggregate computed on full group (future leakage)
            suspect_mask = eq_full & (~eq_prior)
            n_suspect = int(suspect_mask.sum())
            if n_suspect > 0:
                results.append({"feature": col, "group_by": group_key, "rows_suspect": n_suspect})

        return {"suspects": results}

    def preprocessing_checks(self) -> Dict[str, Any]:
        df = self.df
        if self.fold_col is None or self.fold_col not in df.columns:
            return {"error": "no fold column available to validate preprocessing timing"}
        numeric = df.select_dtypes(include=[np.number]).columns.tolist()
        exclude = {self.timestamp_col, self.fold_col, self.target_col}
        numeric = [c for c in numeric if c not in exclude]
        findings = []
        for f in numeric:
            per_fold = []
            for fold in df[self.fold_col].unique():
                train_mask = df[self.fold_col] != fold
                val_mask = df[self.fold_col] == fold
                if train_mask.sum() < 2 or val_mask.sum() < 1:
                    continue
                train_mean = df.loc[train_mask, f].mean()
                train_std = df.loc[train_mask, f].std()
                if pd.isna(train_std) or train_std == 0:
                    continue
                val_mean = df.loc[val_mask, f].mean()
                # after standardizing val with train stats, mean should not be near zero unless preprocessing used train stats
                standardized_val_mean = (val_mean - train_mean) / train_std
                per_fold.append(float(standardized_val_mean))
            if per_fold:
                # if standardized_val_mean across folds is far from zero consistently, flag
                avg = float(np.nanmean(per_fold))
                if abs(avg) > 0.1:
                    findings.append({"feature": f, "avg_standardized_val_mean": avg})
        return {"preprocessing_issues": findings}

    def calibration_timing_check(self) -> Dict[str, Any]:
        df = self.df
        raw_cols = [c for c in df.columns if "pred" in c and "calib" not in c]
        calib_cols = [c for c in df.columns if "calib" in c or "calibr" in c]
        report = {"issues": []}
        if not raw_cols or not calib_cols:
            report["note"] = "no obvious raw/calibrated prediction columns found"
            return report
        raw = raw_cols[0]
        calib = calib_cols[0]
        if self.fold_col is None or self.target_col is None:
            report["error"] = "need fold_col and target_col to verify calibration timing"
            return report
        # Train a simple isotonic regression on train folds and compare
        from sklearn.isotonic import IsotonicRegression

        violations = []
        for fold in df[self.fold_col].unique():
            train_mask = df[self.fold_col] != fold
            val_mask = df[self.fold_col] == fold
            if train_mask.sum() < 10 or val_mask.sum() < 1:
                continue
            ir = IsotonicRegression(out_of_bounds="clip")
            try:
                ir.fit(df.loc[train_mask, raw], df.loc[train_mask, self.target_col])
                pred_calib_train = ir.transform(df.loc[val_mask, raw])
                # compare stored calibrated values to train-only mapping
                stored = df.loc[val_mask, calib].values
                # if stored equals mapping computed on full data, that's suspicious. We'll also compute full-data mapping
                ir_full = IsotonicRegression(out_of_bounds="clip")
                ir_full.fit(df[raw], df[self.target_col])
                full_map = ir_full.transform(df.loc[val_mask, raw])
                # If stored matches full_map more closely than pred_calib_train, flag
                diff_train = np.mean(np.abs(stored - pred_calib_train))
                diff_full = np.mean(np.abs(stored - full_map))
                if diff_full + 1e-12 < diff_train:
                    violations.append({"fold": int(fold) if isinstance(fold, (int, np.integer)) else fold, "diff_train": float(diff_train), "diff_full": float(diff_full)})
            except Exception:
                continue

        report["violations"] = violations
        report["status"] = "pass" if not violations else "fail"
        return report

    def replay_aggregate_check(self, sample_n: int = 200) -> Dict[str, Any]:
        """Recompute simple prior-only group aggregates for a sample of rows and compare."""
        df = self.df
        groups = [c for c in ["horse_id", "trainer_id", "jockey_id"] if c in df.columns]
        if not groups:
            return {"error": "no group id columns for replay aggregate check"}
        group_key = groups[0]
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        exclude = {self.timestamp_col, self.fold_col, self.target_col}
        candidate = [c for c in numeric_cols if c not in exclude]
        suspects = []
        sample = df.sample(n=min(sample_n, len(df)), random_state=0)
        for idx, row in sample.iterrows():
            key = row[group_key]
            ts = row[self.timestamp_col]
            group_hist = df[(df[group_key] == key) & (df[self.timestamp_col] < ts)].sort_values(self.timestamp_col)
            if group_hist.empty:
                continue
            # compute prior-only mean for candidate cols
            prior_mean = group_hist[candidate].mean()
            for c in candidate:
                stored = row.get(c, np.nan)
                if pd.isna(stored) or pd.isna(prior_mean.get(c, np.nan)):
                    continue
                # if stored equals full-group mean but not prior_mean, flag
                full_mean = df.loc[df[group_key] == key, c].mean()
                if np.isclose(stored, full_mean, atol=1e-8) and not np.isclose(stored, prior_mean.get(c, np.nan), atol=1e-8):
                    suspects.append({"index": int(idx), "feature": c, "group": key, "timestamp": str(ts)})

        return {"suspects": suspects}

    def audit(self) -> Tuple[Dict[str, Any], pd.DataFrame]:
        report: Dict[str, Any] = {}
        report["temporal_checks"] = self.temporal_checks()
        report["fit_timing"] = self.fit_timing_verification()
        report["aggregation_contamination"] = self.aggregation_contamination_check()
        report["preprocessing"] = self.preprocessing_checks()
        report["calibration_timing"] = self.calibration_timing_check()
        report["replay_check"] = self.replay_aggregate_check()

        # compile suspicious rows from aggregation and replay checks
        suspects = []
        agg = report.get("aggregation_contamination", {}).get("suspects", [])
        for s in agg:
            suspects.append({"feature": s["feature"], "reason": "agg_full_vs_prior", "rows_suspect": s["rows_suspect"]})
        replay = report.get("replay_check", {}).get("suspects", [])
        for s in replay:
            suspects.append({"index": s["index"], "feature": s["feature"], "reason": "replay_full_vs_prior"})

        suspects_df = pd.DataFrame(suspects)
        return report, suspects_df


def save_report(report: Dict[str, Any], out_path: str) -> None:
    def _serialize(o):
        if isinstance(o, pd.DataFrame):
            return o.to_dict(orient="records")
        if pd.isna(o):
            return None
        if isinstance(o, (np.integer, np.floating)):
            return o.item()
        if isinstance(o, (np.ndarray,)):
            return o.tolist()
        if hasattr(o, "isoformat"):
            try:
                return str(o)
            except Exception:
                return repr(o)
        return o

    def _walk(x):
        if isinstance(x, dict):
            return {k: _walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [_walk(v) for v in x]
        return _serialize(x)

    safe = _walk(report)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(safe, f, indent=2, ensure_ascii=False, default=str)
