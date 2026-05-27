"""Automatic probability calibrator refit from settled bets.csv rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from core.prediction.calibration import ProbabilityCalibrator
from learning.reliability_curve import ReliabilityCurveAnalyzer


class CalibrationRefitJob:
    """Refit ProbabilityCalibrator when enough settled bets accumulate."""

    def __init__(
        self,
        bets_log_path: str = "logs/bets.csv",
        calibrator_path: str = "models/calibrator_state.json",
        min_samples: int = 100,
        ideal_samples: int = 500,
        recalibration_ece_threshold: float = 0.06,
        slippage_alert_threshold: float = -0.10,
        slippage_window: int = 20,
    ):
        self.bets_log_path = Path(bets_log_path)
        self.calibrator_path = Path(calibrator_path)
        self.min_samples = int(min_samples)
        self.ideal_samples = int(ideal_samples)
        self.recalibration_ece_threshold = float(recalibration_ece_threshold)
        self.slippage_alert_threshold = float(slippage_alert_threshold)
        self.slippage_window = int(slippage_window)
        self.last_result: Optional[Dict[str, Any]] = None
        self._samples_since_last_fit = 0

    def _load_settled_rows(self) -> pd.DataFrame:
        if not self.bets_log_path.exists():
            return pd.DataFrame()

        frame = pd.read_csv(self.bets_log_path)
        if frame.empty or "hit" not in frame.columns:
            return pd.DataFrame()

        settled = frame[frame["hit"].astype(str).str.strip() != ""].copy()
        settled["hit"] = pd.to_numeric(settled["hit"], errors="coerce")
        settled = settled.dropna(subset=["hit"])
        return settled

    def _extract_probability(self, row: pd.Series) -> Optional[float]:
        for column in ("calibrated_probability", "probability"):
            if column in row.index and pd.notna(row[column]):
                try:
                    return float(row[column])
                except (TypeError, ValueError):
                    continue
        return None

    def slippage_triggered(self, frame: Optional[pd.DataFrame] = None) -> bool:
        data = frame if frame is not None else self._load_settled_rows()
        if data.empty or "slippage_pct" not in data.columns:
            return False

        recent = pd.to_numeric(data["slippage_pct"], errors="coerce").dropna().tail(
            self.slippage_window
        )
        if recent.empty:
            return False
        return float(recent.mean()) <= self.slippage_alert_threshold

    def reliability_triggered(self, analyzer: ReliabilityCurveAnalyzer) -> bool:
        recommendation = analyzer.recommendation()
        return recommendation in {
            "RECALIBRATION_REQUIRED",
            "STOP_HIGH_CONFIDENCE_BETS",
        }

    def should_refit(
        self,
        *,
        force: bool = False,
        reliability_analyzer: Optional[ReliabilityCurveAnalyzer] = None,
    ) -> tuple[bool, str]:
        if force:
            return True, "FORCED"

        settled = self._load_settled_rows()
        count = len(settled)

        if count < self.min_samples:
            return False, f"INSUFFICIENT_SAMPLES:{count}/{self.min_samples}"

        if self.slippage_triggered(settled):
            return True, "SLIPPAGE_ALERT"

        if reliability_analyzer is not None and self.reliability_triggered(
            reliability_analyzer
        ):
            return True, "RELIABILITY_ALERT"

        if count >= self.ideal_samples and self._samples_since_last_fit >= self.min_samples:
            return True, "PERIODIC_REFIT"

        if self._samples_since_last_fit >= self.min_samples:
            analysis = self._analyze_ece(settled)
            ece = analysis.get("ece", 0.0)
            if ece >= self.recalibration_ece_threshold:
                return True, f"ECE_THRESHOLD:{ece:.4f}"

        return False, f"STABLE:{count}"

    def _analyze_ece(self, settled: pd.DataFrame) -> Dict[str, float]:
        probs = []
        hits = []
        for _, row in settled.iterrows():
            prob = self._extract_probability(row)
            if prob is None:
                continue
            probs.append(prob)
            hits.append(float(row["hit"]))

        if not probs:
            return {"ece": 0.0, "brier": 0.0, "count": 0}

        calibrator = ProbabilityCalibrator()
        diag = calibrator.diagnostics(probs, hits)
        return {
            "ece": float(diag.get("ece", 0.0)),
            "brier": float(diag.get("brier", 0.0)),
            "count": len(probs),
        }

    def fit_from_bets_log(
        self,
        calibrator: Optional[ProbabilityCalibrator] = None,
    ) -> Dict[str, Any]:
        settled = self._load_settled_rows()
        probs = []
        hits = []

        for _, row in settled.iterrows():
            prob = self._extract_probability(row)
            if prob is None:
                continue
            probs.append(prob)
            hits.append(int(row["hit"]))

        if len(probs) < self.min_samples:
            result = {
                "status": "SKIPPED",
                "reason": "insufficient_samples",
                "count": len(probs),
                "min_samples": self.min_samples,
            }
            self.last_result = result
            return result

        target = calibrator or ProbabilityCalibrator()
        target.fit_from_logs(probs, hits)

        self.calibrator_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "shrink": target.shrink,
            "min_prob": target.min_prob,
            "max_prob": target.max_prob,
            "bin_edges": target.bin_edges.tolist() if target.bin_edges is not None else None,
            "bin_factors": target.bin_factors.tolist()
            if target.bin_factors is not None
            else None,
            "sample_count": len(probs),
        }
        self.calibrator_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

        diag = target.diagnostics(probs, hits)
        self._samples_since_last_fit = 0

        result = {
            "status": "FITTED",
            "count": len(probs),
            "ece": diag.get("ece"),
            "brier": diag.get("brier"),
            "reliability": diag.get("reliability"),
            "calibrator_path": str(self.calibrator_path),
        }
        self.last_result = result
        return result

    def load_calibrator(
        self,
        calibrator: Optional[ProbabilityCalibrator] = None,
    ) -> ProbabilityCalibrator:
        target = calibrator or ProbabilityCalibrator()
        if not self.calibrator_path.exists():
            return target

        payload = json.loads(self.calibrator_path.read_text(encoding="utf-8"))
        target.shrink = float(payload.get("shrink", target.shrink))
        target.min_prob = float(payload.get("min_prob", target.min_prob))
        target.max_prob = float(payload.get("max_prob", target.max_prob))

        edges = payload.get("bin_edges")
        factors = payload.get("bin_factors")
        if edges is not None and factors is not None:
            target.bin_edges = np.array(edges)
            target.bin_factors = np.array(factors)

        return target

    def maybe_refit(
        self,
        *,
        force: bool = False,
        reliability_analyzer: Optional[ReliabilityCurveAnalyzer] = None,
        calibrator: Optional[ProbabilityCalibrator] = None,
    ) -> Dict[str, Any]:
        should, reason = self.should_refit(
            force=force,
            reliability_analyzer=reliability_analyzer,
        )
        if not should:
            result = {"status": "SKIPPED", "reason": reason}
            self.last_result = result
            return result

        fit_result = self.fit_from_bets_log(calibrator=calibrator)
        fit_result["trigger"] = reason
        return fit_result

    def record_new_settlement(self, count: int = 1) -> None:
        self._samples_since_last_fit += int(count)
