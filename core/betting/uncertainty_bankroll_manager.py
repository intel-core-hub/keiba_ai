from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.betting.defensive_mode_controller import DefensiveModeController
from core.betting.risk_manager import RiskConfig, RiskManager
from core.betting.uncertainty_monitor import UncertaintyMonitor
from core.betting.uncertainty_sizing import UncertaintySizer


@dataclass
class UncertaintyBankrollConfig:
    wrap_existing_manager: bool = True


class UncertaintyBankrollManager:
    def __init__(
        self,
        base_manager: Optional[RiskManager] = None,
        risk_config: Optional[RiskConfig] = None,
        sizing: Optional[UncertaintySizer] = None,
        monitor: Optional[UncertaintyMonitor] = None,
        controller: Optional[DefensiveModeController] = None,
    ):
        self.base = base_manager or RiskManager(risk_config or RiskConfig())
        self.sizer = sizing or UncertaintySizer()
        self.monitor = monitor or UncertaintyMonitor()
        self.controller = controller or DefensiveModeController(self.monitor)

        self.last_uncertainty_score = 0.0
        self.last_drift_score = 0.0
        self.last_calibration_gap = 0.0
        self.last_edge_quality = 0.0
        self.last_global_exposure_multiplier = 1.0
        self.last_uncertainty_multiplier = 1.0

    def update_uncertainty_state(
        self,
        uncertainty_score: float | None = None,
        drift_score: float | None = None,
        calibration_gap: float | None = None,
        drawdown: float | None = None,
        roi: float | None = None,
        edge: float | None = None,
        profit: float | None = None,
        edge_quality: float | None = None,
    ):
        if uncertainty_score is None:
            return self.status()

        self.last_uncertainty_score = float(uncertainty_score)
        self.last_drift_score = float(drift_score or 0.0)
        self.last_calibration_gap = float(calibration_gap or 0.0)
        self.last_edge_quality = float(edge_quality or 0.0)

        self.controller.update(
            uncertainty_score=self.last_uncertainty_score,
            drift_score=drift_score,
            calibration_gap=calibration_gap,
            drawdown=drawdown,
            roi=roi,
            edge=edge,
            profit=profit,
        )

        self.last_uncertainty_multiplier = self.sizer.size_multiplier(
            self.last_uncertainty_score,
            drift_score=drift_score,
        )
        self.last_global_exposure_multiplier = self.controller.exposure_multiplier()
        return self.status()

    def reset_race_risk(self):
        self.base.reset_race_risk()

    def update_after_race(self, profit: float):
        self.base.update_after_race(profit)

    def drawdown(self):
        return self.base.drawdown()

    def profit_ratio(self):
        return self.base.profit_ratio()

    @property
    def bankroll(self):
        return self.base.bankroll

    def risk_multiplier(self) -> float:
        if self.controller.no_bet(self.last_uncertainty_score, self.last_drift_score):
            return 0.0

        base_mult = float(self.base.risk_multiplier())
        return float(max(0.0, base_mult * self.last_uncertainty_multiplier * self.last_global_exposure_multiplier))

    def max_bet_size(self):
        base = float(self.base.max_bet_size())
        return int(max(0.0, base * self.last_global_exposure_multiplier))

    def register_bet(self, size: float):
        self.base.register_bet(size)

    def can_bet(self) -> bool:
        if self.controller.no_bet(self.last_uncertainty_score, self.last_drift_score):
            return False
        return self.base.can_bet()

    def adjust_bet_sizer(self, bet_sizer):
        try:
            if hasattr(bet_sizer, "cfg") and hasattr(bet_sizer.cfg, "min_edge"):
                if self.last_uncertainty_score >= 0.65:
                    bet_sizer.cfg.min_edge = max(bet_sizer.cfg.min_edge, 0.05)
                elif self.last_uncertainty_score >= 0.50:
                    bet_sizer.cfg.min_edge = max(bet_sizer.cfg.min_edge, 0.03)
        except Exception:
            pass

    def status(self):
        status = self.base.status()
        status.update({
            "uncertainty_score": round(self.last_uncertainty_score, 6),
            "drift_score": round(self.last_drift_score, 6),
            "calibration_gap": round(self.last_calibration_gap, 6),
            "edge_quality": round(self.last_edge_quality, 6),
            "uncertainty_multiplier": round(self.last_uncertainty_multiplier, 6),
            "global_exposure_multiplier": round(self.last_global_exposure_multiplier, 6),
            "defensive_mode": self.controller.mode,
            "defensive_reason": self.controller.last_reason,
        })
        return status