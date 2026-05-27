from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class UncertaintySizingConfig:
    low_threshold: float = 0.20
    high_threshold: float = 0.75
    reduce_floor: float = 0.20
    defensive_floor: float = 0.10
    drift_threshold: float = 0.05
    drift_penalty: float = 0.60
    exposure_reduce_floor: float = 0.35


class UncertaintySizer:
    def __init__(self, cfg: Optional[UncertaintySizingConfig] = None):
        self.cfg = cfg or UncertaintySizingConfig()

    def size_multiplier(self, uncertainty_score: float, drift_score: float | None = None) -> float:
        u = self._clamp(uncertainty_score)

        if u >= self.cfg.high_threshold:
            return 0.0

        if u <= self.cfg.low_threshold:
            mult = 1.0
        else:
            span = max(1e-6, self.cfg.high_threshold - self.cfg.low_threshold)
            progress = (u - self.cfg.low_threshold) / span
            mult = 1.0 - progress * (1.0 - self.cfg.reduce_floor)

        if drift_score is not None and float(drift_score) > self.cfg.drift_threshold:
            mult *= max(self.cfg.defensive_floor, 1.0 - float(drift_score) * self.cfg.drift_penalty)

        return float(max(0.0, min(1.0, mult)))

    def exposure_multiplier(self, rolling_uncertainty: float | None = None, drift_score: float | None = None) -> float:
        exposure = 1.0

        if rolling_uncertainty is not None:
            rolling = self._clamp(rolling_uncertainty)
            if rolling > self.cfg.low_threshold:
                exposure *= max(
                    self.cfg.exposure_reduce_floor,
                    1.0 - (rolling - self.cfg.low_threshold) / max(1e-6, self.cfg.high_threshold - self.cfg.low_threshold),
                )

        if drift_score is not None and float(drift_score) > self.cfg.drift_threshold:
            exposure *= max(self.cfg.exposure_reduce_floor, 1.0 - float(drift_score) * 2.0)

        return float(max(0.0, min(1.0, exposure)))

    def no_bet(self, uncertainty_score: float, drift_score: float | None = None) -> bool:
        u = self._clamp(uncertainty_score)
        if u >= self.cfg.high_threshold:
            return True
        if drift_score is not None and u >= self.cfg.low_threshold and float(drift_score) >= self.cfg.drift_threshold * 2:
            return True
        return False

    def _clamp(self, value: float) -> float:
        return float(max(0.0, min(1.0, float(value))))