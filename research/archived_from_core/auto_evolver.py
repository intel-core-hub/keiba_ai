# core/adaptation/auto_evolver.py

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from ..config_manager import ConfigManager

from learning.performance_analyzer import PerformanceAnalyzer
from learning.strategy_updater import StrategyUpdater


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
class AutoEvolverResult:
	metrics: Dict[str, Any]
	settings_before: Dict[str, Any]
	settings_after: Dict[str, Any]
	settings_path: str
	approved: bool = True
	skipped_reason: Optional[str] = None
	diff: Dict[str, Any] = None


class AutoEvolver:
	"""learning.auto_evolver の処理を core/adaptation から呼ぶためのラッパー。"""

	def __init__(
		self,
		settings_path: str = "config/settings.yaml",
		analyzer: Optional[PerformanceAnalyzer] = None,
		updater: Optional[StrategyUpdater] = None,
	):
		self.settings_path = settings_path
		self.analyzer = analyzer or PerformanceAnalyzer()
		self.updater = updater or StrategyUpdater()

	def load_settings(self) -> Dict[str, Any]:
		path = Path(self.settings_path)
		if not path.exists():
			return {}

		with path.open("r", encoding="utf-8") as handle:
			data = yaml.safe_load(handle) or {}

		return _sync_kelly_keys(data)

	def save_settings(self, settings: Dict[str, Any]) -> None:
		# Use ConfigManager to persist settings asynchronously and atomically
		mgr = ConfigManager(self.settings_path)
		payload = _sync_kelly_keys(settings)
		mgr.save_async(payload)

	def evolve(
		self,
		governance_result: Optional[Any] = None,
		audit_logger: Any = None,
		memory: Any = None,
	) -> AutoEvolverResult:
		approved = True
		if governance_result is not None:
			if hasattr(governance_result, "approved"):
				approved = governance_result.approved
			elif isinstance(governance_result, dict):
				approved = governance_result.get("approved", False)
			
		if not approved:
			settings_before = self.load_settings()
			return AutoEvolverResult(
				metrics={},
				settings_before=settings_before,
				settings_after=settings_before,
				settings_path=self.settings_path,
				approved=False,
				skipped_reason="governance rejected update",
				diff={},
			)

		metrics = self.analyzer.analyze()
		settings_before = self.load_settings()
		updated_settings = self.updater.update(metrics, deepcopy(settings_before))
		updated_settings = _sync_kelly_keys(updated_settings)
		self.save_settings(updated_settings)

		diff = {
			key: {
				"before": settings_before.get(key),
				"after": updated_settings.get(key),
			}
			for key in sorted(set(settings_before) | set(updated_settings))
			if settings_before.get(key) != updated_settings.get(key)
		}

		if audit_logger is not None:
			audit_logger.log(
				category="AUTO_EVOLVER",
				action="SETTINGS_UPDATED",
				severity="INFO",
				metadata={
					"settings_path": self.settings_path,
					"diff": diff,
				},
			)

		if memory is not None:
			memory.record_event(
				category="EVOLUTION",
				title="Auto Evolver Update",
				content=f"updated {len(diff)} settings",
				severity=0.0,
				tags=["auto_evolver", "settings"],
			)

		return AutoEvolverResult(
			metrics=metrics,
			settings_before=settings_before,
			settings_after=updated_settings,
			settings_path=self.settings_path,
			approved=True,
			skipped_reason=None,
			diff=diff,
		)


def evolve(settings_path: str = "config/settings.yaml") -> AutoEvolverResult:
	return AutoEvolver(settings_path=settings_path).evolve()

