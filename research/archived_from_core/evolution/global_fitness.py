from dataclasses import dataclass
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


@dataclass(frozen=True)
class GlobalFitnessWeights:
    profit: float = 0.45
    drawdown: float = 0.25
    stability: float = 0.20
    survival: float = 0.10


class GlobalFitness:
    def __init__(self, weights: GlobalFitnessWeights | None = None):
        self.weights = weights or GlobalFitnessWeights()

    def compute(self, stats: Any) -> float:
        profit = _extract_value(stats, "profit", _extract_value(stats, "roi", 0.0))
        drawdown = _extract_value(stats, "drawdown", 0.0)
        stability = _extract_value(stats, "stability", 0.0)
        survival = _extract_value(stats, "survival", 0.0)

        return (
            self.weights.profit * profit
            + self.weights.drawdown * (1.0 - drawdown)
            + self.weights.stability * stability
            + self.weights.survival * survival
        )