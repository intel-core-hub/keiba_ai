# core/adaptation/recursive_optimizer.py

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def _sync_kelly_keys(settings: Dict[str, Any]) -> Dict[str, Any]:
	normalized = dict(settings)

	if "kelly_fraction" not in normalized and "kelly_mult" in normalized:
		normalized["kelly_fraction"] = normalized["kelly_mult"]

	if "kelly_mult" not in normalized and "kelly_fraction" in normalized:
		normalized["kelly_mult"] = normalized["kelly_fraction"]

	if "kelly_fraction" in normalized:
		normalized["kelly_mult"] = normalized["kelly_fraction"]

	return normalized


@dataclass
class OptimizationTrace:
	key: str
	old_value: Any
	new_value: Any
	reason: str


@dataclass
class OptimizationResult:
	settings: Dict[str, Any]
	traces: List[OptimizationTrace] = field(default_factory=list)
	depth: int = 0
	converged: bool = False


class RecursiveOptimizer:
	"""Kelly fraction や min_edge などの設定を再帰的に微調整する。"""

	def __init__(
		self,
		settings_path: str = "config/settings.yaml",
		max_depth: int = 3,
	):
		self.settings_path = settings_path
		self.max_depth = max_depth

	def load_settings(self) -> Dict[str, Any]:
		path = Path(self.settings_path)
		if not path.exists():
			return {}

		with path.open("r", encoding="utf-8") as handle:
			data = yaml.safe_load(handle) or {}

		return _sync_kelly_keys(data)

	def save_settings(self, settings: Dict[str, Any]) -> None:
		path = Path(self.settings_path)
		path.parent.mkdir(parents=True, exist_ok=True)

		payload = _sync_kelly_keys(settings)
		with path.open("w", encoding="utf-8") as handle:
			yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)

	def optimize(
		self,
		metrics: Dict[str, Any],
		settings: Optional[Dict[str, Any]] = None,
		save: bool = True,
	) -> OptimizationResult:
		current = _sync_kelly_keys(settings or self.load_settings())
		result = self._optimize_recursive(current, metrics, depth=self.max_depth)

		if save:
			self.save_settings(result.settings)

		return result

	def _optimize_recursive(
		self,
		settings: Dict[str, Any],
		metrics: Dict[str, Any],
		depth: int,
	) -> OptimizationResult:
		candidate = deepcopy(settings)
		traces: List[OptimizationTrace] = []
		stability = metrics.get("stability", {}) if isinstance(metrics.get("stability", {}), dict) else {}

		brier = float(
			metrics.get(
				"mean_brier",
				metrics.get("brier", metrics.get("brier_score", 0.0)),
			)
			or 0.0
		)
		roi = float(metrics.get("roi", metrics.get("roi_mean", stability.get("roi_mean", 0.0))) or 0.0)
		drawdown = float(metrics.get("drawdown", metrics.get("max_drawdown", 0.0)) or 0.0)
		volatility = float(metrics.get("volatility", stability.get("roi_std", 0.0)) or 0.0)
		drift = float(metrics.get("drift_score", stability.get("drift_score", 0.0)) or 0.0)
		regime = str(metrics.get("regime", "NORMAL") or "NORMAL")

		def set_value(key: str, value: Any) -> None:
			old_value = candidate.get(key)
			if old_value != value:
				traces.append(
					OptimizationTrace(
						key=key,
						old_value=old_value,
						new_value=value,
						reason="rule-based adjustment",
					)
				)
			candidate[key] = value

		def clamp_relative(value: float, anchor: float, max_ratio: float) -> float:
			if anchor <= 0:
				return value
			lower = anchor * (1.0 - max_ratio)
			upper = anchor * (1.0 + max_ratio)
			return max(lower, min(upper, value))

		kelly_fraction = float(candidate.get("kelly_fraction", 0.25))
		min_edge = float(candidate.get("min_edge", 0.02))
		max_fraction = float(candidate.get("max_fraction", 0.15))
		probability_shrink = float(candidate.get("probability_shrink", 0.9))
		top_n = int(candidate.get("top_n", 3))
		anchor_top_n = int(settings.get("top_n", top_n) or top_n)
		min_odds = float(candidate.get("min_odds", 1.0))

		if brier > 0.20:
			kelly_fraction *= 0.90
			max_fraction *= 0.95
			min_edge += 0.005
			probability_shrink = min(1.0, probability_shrink + 0.02)
		elif brier < 0.13:
			kelly_fraction *= 1.04
			min_edge -= 0.002
			probability_shrink = max(0.5, probability_shrink - 0.01)

		if roi > 0.0:
			kelly_fraction *= 1.02
			min_edge -= 0.001
		elif roi < -0.05:
			kelly_fraction *= 0.95
			min_edge += 0.003

		if drawdown > 0.20 or volatility > 0.20:
			kelly_fraction *= 0.88
			max_fraction *= 0.92
			top_n = max(2, top_n - 1)
			min_edge += 0.003

		if drift > 0.03:
			kelly_fraction *= 0.92
			max_fraction *= 0.95
			min_edge += 0.002

		if regime == "CHAOS":
			kelly_fraction *= 0.75
			min_edge += 0.010
			top_n = max(2, top_n - 1)

		if regime == "FAVORITE_DOMINANCE":
			min_edge += 0.002

		kelly_fraction = clamp_relative(kelly_fraction, float(settings.get("kelly_fraction", 0.25) or 0.25), 0.15)
		max_fraction = clamp_relative(max_fraction, float(settings.get("max_fraction", 0.15) or 0.15), 0.15)
		min_edge = clamp_relative(min_edge, max(0.001, float(settings.get("min_edge", 0.02) or 0.02)), 0.25)

		set_value("kelly_fraction", max(0.05, min(0.25, kelly_fraction)))
		set_value("max_fraction", max(0.05, min(0.20, max_fraction)))
		set_value("min_edge", max(0.0, min(0.10, min_edge)))
		set_value("probability_shrink", max(0.5, min(1.0, probability_shrink)))
		top_n = int(max(anchor_top_n - 1, min(anchor_top_n + 1, top_n)))
		set_value("top_n", int(max(2, min(5, top_n))))
		set_value("min_odds", max(1.0, min(10.0, min_odds)))

		candidate = _sync_kelly_keys(candidate)

		if depth <= 1 or candidate == settings:
			return OptimizationResult(
				settings=candidate,
				traces=traces,
				depth=self.max_depth - depth + 1,
				converged=True,
			)

		nested = self._optimize_recursive(candidate, metrics, depth - 1)
		nested.traces = traces + nested.traces
		nested.depth = self.max_depth - depth + 1
		return nested

