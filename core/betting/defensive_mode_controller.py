from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.betting.uncertainty_monitor import UncertaintyMonitor


@dataclass
class DefensiveModeConfig:
    uncertainty_high: float = 0.65
    uncertainty_halt: float = 0.80
    drift_high: float = 0.08
    deterioration_floor: float = 0.03
    defensive_exposure: float = 0.45
    halt_exposure: float = 0.0


class DefensiveModeController:
    def __init__(
        self,
        monitor: Optional[UncertaintyMonitor] = None,
        cfg: Optional[DefensiveModeConfig] = None,
    ):
        self.monitor = monitor or UncertaintyMonitor()
        self.cfg = cfg or DefensiveModeConfig()
        self.mode = "NORMAL"
        self.last_reason = "OK"

    def update(
        self,
        uncertainty_score: float | None = None,
        drift_score: float | None = None,
        calibration_gap: float | None = None,
        drawdown: float | None = None,
        roi: float | None = None,
        edge: float | None = None,
        profit: float | None = None,
    ):
        if uncertainty_score is None:
            return self.status()

        self.monitor.record(
            uncertainty_score=float(uncertainty_score),
            drift_score=drift_score,
            calibration_gap=calibration_gap,
            drawdown=drawdown,
            roi=roi,
            edge=edge,
            profit=profit,
        )

        summary = self.monitor.summary()
        rolling = float(summary.get("rolling_uncertainty", 0.0))
        deteriorating = bool(summary.get("deteriorating", False))
        drift_worsening = bool(summary.get("drift_worsening", False))
        drift_now = float(drift_score or 0.0)

        if uncertainty_score >= self.cfg.uncertainty_halt or (deteriorating and drift_now >= self.cfg.drift_high):
            self.mode = "HALT"
            self.last_reason = "UNCERTAINTY_AND_DRIFT"
        elif uncertainty_score >= self.cfg.uncertainty_high or drift_now >= self.cfg.drift_high or drift_worsening:
            self.mode = "DEFENSIVE"
            self.last_reason = "DEFENSIVE_MODE"
        elif rolling >= self.cfg.uncertainty_high and deteriorating:
            self.mode = "DEFENSIVE"
            self.last_reason = "ROLLING_UNCERTAINTY"
        else:
            self.mode = "NORMAL"
            self.last_reason = "OK"

        return self.status()

    def exposure_multiplier(self) -> float:
        if self.mode == "HALT":
            return float(self.cfg.halt_exposure)
        if self.mode == "DEFENSIVE":
            return float(self.cfg.defensive_exposure)
        return 1.0

    def no_bet(self, uncertainty_score: float | None = None, drift_score: float | None = None) -> bool:
        if self.mode == "HALT":
            return True
        if uncertainty_score is None:
            return False
        if float(uncertainty_score) >= self.cfg.uncertainty_halt:
            return True
        if drift_score is not None and float(drift_score) >= self.cfg.drift_high and float(uncertainty_score) >= self.cfg.uncertainty_high:
            return True
        return False

    def status(self):
        summary = self.monitor.summary()
        summary.update({
            "mode": self.mode,
            "reason": self.last_reason,
            "exposure_multiplier": round(self.exposure_multiplier(), 6),
            "halted": self.mode == "HALT",
        })
        return summary