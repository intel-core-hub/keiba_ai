# core/adaptation/__init__.py

from .auto_retrainer import AutoRetrainer
from .auto_evolver import AutoEvolver, AutoEvolverResult, evolve
from .meta_learner import MetaLearner
from .strategy_evolver import StrategyEvolver
from .recursive_optimizer import (
	RecursiveOptimizer,
	OptimizationResult,
	OptimizationTrace,
)

__all__ = [
	"AutoRetrainer",
	"AutoEvolver",
	"AutoEvolverResult",
	"evolve",
	"MetaLearner",
	"StrategyEvolver",
	"RecursiveOptimizer",
	"OptimizationResult",
	"OptimizationTrace",
]

