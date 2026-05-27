from dataclasses import dataclass
from typing import Optional


@dataclass
class CalibrationRiskConfig:
    # ECE thresholds
    ece_warn: float = 0.04
    ece_bad: float = 0.07

    # Brier thresholds
    brier_warn: float = 0.20
    brier_bad: float = 0.24

    # Reliability thresholds
    reliability_warn: float = 0.94
    reliability_bad: float = 0.90

    # Drift thresholds
    drift_warn: float = 0.10
    drift_bad: float = 0.25

    # Multipliers
    ece_warn_mult: float = 0.80
    ece_bad_mult: float = 0.50
    brier_warn_mult: float = 0.75
    brier_bad_mult: float = 0.55
    reliability_warn_mult: float = 0.85
    reliability_bad_mult: float = 0.70

    # Drift exposure reductions (applied to max_race_exposure)
    drift_warn_exposure_mult: float = 0.75
    drift_bad_exposure_mult: float = 0.45

    # Kelly and min_edge clamps
    min_kelly_fraction: float = 0.02
    min_edge_cap: float = 0.05


class CalibrationRiskManager:
    """
    Wraps an existing RiskManager and applies calibration-aware
    multipliers for sizing and exposure control.

    Interface mirrors RiskManager so it can be used in place of it.
    """

    def __init__(self, base_risk_manager, cfg: Optional[CalibrationRiskConfig] = None):

        self.base = base_risk_manager
        self.cfg = cfg or CalibrationRiskConfig()

        # last calibration state
        self.calibration_state = {}

        # computed multipliers
        self._calibration_mult = 1.0
        self._exposure_mult = 1.0
        self._kelly_scale = 1.0
        self._min_edge_override = None

        # optional halt flag for severe drift
        self._halted = False

    # -------------------------------------------------
    # Calibration updates
    # -------------------------------------------------

    def update_calibration_state(self, state: dict):
        if not state:
            return

        self.calibration_state.update(state)

        # compute calibration multiplier
        mult = 1.0

        ece = float(self.calibration_state.get("mean_ece", self.calibration_state.get("ece") or 0.0) or 0.0)
        brier = float(self.calibration_state.get("mean_brier", self.calibration_state.get("brier") or 0.0) or 0.0)
        reliability = float(self.calibration_state.get("mean_reliability", self.calibration_state.get("reliability") or 1.0) or 1.0)
        drift = float(self.calibration_state.get("drift_score") or 0.0)
        mean_uncertainty = float(self.calibration_state.get("mean_uncertainty") or 0.0)

        # ECE penalties
        if ece > self.cfg.ece_bad:
            mult *= self.cfg.ece_bad_mult
        elif ece > self.cfg.ece_warn:
            mult *= self.cfg.ece_warn_mult

        # Brier penalties
        if brier > self.cfg.brier_bad:
            mult *= self.cfg.brier_bad_mult
        elif brier > self.cfg.brier_warn:
            mult *= self.cfg.brier_warn_mult

        # Reliability penalties (lower reliability -> penalize)
        if reliability < self.cfg.reliability_bad:
            mult *= self.cfg.reliability_bad_mult
        elif reliability < self.cfg.reliability_warn:
            mult *= self.cfg.reliability_warn_mult

        # Uncertainty: gentle linear scaling down to 0.2 at high uncertainty
        if mean_uncertainty and mean_uncertainty > 0:
            u_mult = max(0.2, 1.0 - mean_uncertainty * 0.6)
            mult *= u_mult

        # clamp
        mult = max(0.0, min(1.0, mult))

        self._calibration_mult = mult

        # exposure controller (based on drift)
        exp_mult = 1.0
        if drift >= self.cfg.drift_bad:
            exp_mult = self.cfg.drift_bad_exposure_mult
            # if extremely bad drift, we set halted flag
            if drift > self.cfg.drift_bad * 1.5:
                self._halted = True
        elif drift >= self.cfg.drift_warn:
            exp_mult = self.cfg.drift_warn_exposure_mult

        self._exposure_mult = float(max(0.0, min(1.0, exp_mult)))

        # kelly scaling: scale down fractional kelly to avoid oversizing
        # ensure not below min_kelly_fraction
        kelly_scale = self._calibration_mult
        self._kelly_scale = max(self.cfg.min_kelly_fraction, kelly_scale)

        # reliability increases min_edge when poor
        if reliability < self.cfg.reliability_bad:
            self._min_edge_override = max(self.cfg.min_edge_cap, None) or self.cfg.min_edge_cap
        elif reliability < self.cfg.reliability_warn:
            self._min_edge_override = max(self.cfg.min_edge_cap * 0.5, None) or (self.cfg.min_edge_cap * 0.5)
        else:
            self._min_edge_override = None

    # -------------------------------------------------
    # Mirror RiskManager interface
    # -------------------------------------------------

    def reset_race_risk(self):
        self.base.reset_race_risk()

    def update_after_race(self, profit: float):
        self.base.update_after_race(profit)

    def drawdown(self):
        return self.base.drawdown()

    def profit_ratio(self):
        return self.base.profit_ratio()

    def risk_multiplier(self) -> float:
        if self._halted:
            return 0.0

        base_mult = float(self.base.risk_multiplier())
        return float(max(0.0, base_mult * self._calibration_mult))

    def max_bet_size(self):
        # reduce available per-race exposure by exposure_mult
        base = self.base.max_bet_size()
        return int(base * self._exposure_mult)

    def register_bet(self, size: float):
        # delegate to base
        self.base.register_bet(size)

    def can_bet(self) -> bool:
        if self._halted:
            return False
        return self.base.can_bet()

    def status(self):
        s = self.base.status()
        s.update(
            {
                "calibration_mult": round(self._calibration_mult, 3),
                "exposure_mult": round(self._exposure_mult, 3),
                "kelly_scale": round(self._kelly_scale, 3),
                "halted": bool(self._halted),
            }
        )
        return s

    # -------------------------------------------------
    # Optional: allow bet_sizer adjustment
    # -------------------------------------------------

    def adjust_bet_sizer(self, bet_sizer):
        try:
            # scale down kelly_fraction
            if hasattr(bet_sizer.cfg, "kelly_fraction"):
                orig = bet_sizer.cfg.kelly_fraction
                bet_sizer.cfg.kelly_fraction = max(
                    self.cfg.min_kelly_fraction, orig * self._kelly_scale
                )

            # increase min_edge when reliability poor
            if self._min_edge_override is not None:
                if hasattr(bet_sizer.cfg, "min_edge"):
                    bet_sizer.cfg.min_edge = max(bet_sizer.cfg.min_edge, self._min_edge_override)
        except Exception:
            # be conservative on failure
            pass
