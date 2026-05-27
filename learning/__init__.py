# learning/__init__.py

from importlib import import_module

_EXPORTS = {
    "BrierMonitor": ("learning.brier_score", "BrierMonitor"),
    "ReliabilityCurveAnalyzer": ("learning.reliability_curve", "ReliabilityCurveAnalyzer"),
    "PerformanceAnalyzer": ("learning.performance_analyzer", "PerformanceAnalyzer"),
    "ROIAnalyzer": ("learning.roi_analyzer", "ROIAnalyzer"),
    "MonteCarloSurvivalSimulator": ("learning.monte_carlo", "MonteCarloSurvivalSimulator"),
    "MetaLearner": ("learning.meta_learner", "MetaLearner"),
    "StrategyEvolver": ("learning.strategy_evolver", "StrategyEvolver"),
    "EdgeFeedback": ("learning.edge_feedback", "EdgeFeedback"),
    "KellyAdaptation": ("learning.kelly_adaptation", "KellyAdaptation"),
    "Trainer": ("learning.trainer", "Trainer"),
    "Updater": ("learning.updater", "Updater"),
    "StrategyUpdater": ("learning.strategy_updater", "StrategyUpdater"),
    "AutoEvolver": ("learning.auto_evolver", "AutoEvolver"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'learning' has no attribute {name!r}")

    module_name, attribute_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
