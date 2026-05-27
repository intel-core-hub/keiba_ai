from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional


@dataclass
class UncertaintyFilterConfig:
    threshold: float = 0.19587       # above this, start shrinking bets (recommended from analysis)
    high_threshold: float = 0.75     # above this, skip bets
    reduce_scale: float = 1.0        # linear scale for reduction
    rolling_window: int = 100        # samples to monitor drift
    drift_alert_delta: float = 0.05  # sustained increase that triggers halt
    drift_check_windows: int = 3     # number of recent windows to compare


class UncertaintyFilter:
    """Uncertainty-based betting filter.

    Responsibilities:
    - Provide multiplier for bet sizing based on uncertainty_score
    - Return skip decision when uncertainty is extreme
    - Track rolling uncertainty for drift detection (trading halt)
    - Provide simple logging hooks
    """

    def __init__(self, cfg: Optional[UncertaintyFilterConfig] = None):
        self.cfg = cfg or UncertaintyFilterConfig()
        self.buffer: Deque[float] = deque(maxlen=self.cfg.rolling_window)
        self.halted = False

    def add_sample(self, uncertainty: float):
        try:
            u = float(uncertainty)
        except Exception:
            return
        self.buffer.append(u)
        self._check_drift()

    def _check_drift(self):
        # simple drift detector: compare mean of recent chunks
        if len(self.buffer) < max(10, self.cfg.rolling_window // 4):
            return

        w = list(self.buffer)
        n = len(w)
        # split into windows
        k = max(1, n // self.cfg.drift_check_windows)
        windows: List[float] = []
        for i in range(self.cfg.drift_check_windows):
            start = max(0, i * k)
            end = min(n, (i + 1) * k)
            if start >= end:
                windows.append(0.0)
            else:
                windows.append(sum(w[start:end]) / (end - start))

        # if recent window(s) show sustained increase beyond delta -> halt
        if windows[-1] - min(windows[:-1]) > self.cfg.drift_alert_delta:
            self.halted = True

    def should_skip(self, uncertainty_score: float) -> (bool, str):
        # extreme no-bet
        if uncertainty_score >= self.cfg.high_threshold:
            return True, 'UNCERTAINTY_TOO_HIGH'

        # below primary threshold: no forced skip
        if uncertainty_score <= self.cfg.threshold:
            return False, 'OK'

        # otherwise allow bet but indicate reduced exposure
        return False, 'REDUCED_EXPOSURE'

    def multiplier(self, uncertainty_score: float) -> float:
        """Return multiplier in [0,1] to scale bet sizing or risk multiplier.

        - >= high_threshold -> 0.0
        - <= threshold -> 1.0
        - linear in between
        """
        u = float(uncertainty_score)
        if u >= self.cfg.high_threshold:
            return 0.0
        if u <= self.cfg.threshold:
            return 1.0
        # linear decay
        denom = max(1e-6, (self.cfg.high_threshold - self.cfg.threshold))
        frac = (u - self.cfg.threshold) / denom
        mult = max(0.0, 1.0 - frac * float(self.cfg.reduce_scale))
        return float(mult)

    def is_halted(self) -> bool:
        return bool(self.halted)

    def status(self) -> dict:
        return {
            'buffer_count': len(self.buffer),
            'mean_uncertainty': float(sum(self.buffer) / len(self.buffer)) if self.buffer else 0.0,
            'halted': self.halted,
            'cfg': self.cfg.__dict__,
        }
