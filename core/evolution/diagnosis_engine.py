from typing import Any


def _extract_value(stats: Any, name: str, default: float = 0.0) -> float:
    if stats is None:
        return float(default)

    if isinstance(stats, dict):
        value = stats.get(name, default)
    else:
        value = getattr(stats, name, default)

    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class DiagnosisEngine:
    def __init__(self, max_drawdown: float = 0.25, max_overfit_score: float = 0.70):
        self.max_drawdown = max_drawdown
        self.max_overfit_score = max_overfit_score

    def diagnose(self, stats: Any) -> str:
        if _extract_value(stats, "drawdown", 0.0) > self.max_drawdown:
            return "RISK_TOO_HIGH"

        if bool(_extract_value(stats, "drift_detected", 0.0)):
            return "REGIME_SHIFT"

        if _extract_value(stats, "overfit_score", 0.0) > self.max_overfit_score:
            return "OVERFITTING"

        return "STABLE"