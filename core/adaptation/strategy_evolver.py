# core/adaptation/strategy_evolver.py

"""Lazy wrapper for StrategyEvolver to avoid importing learning at module import.

This prevents pulling research code into the runtime import graph. Use
`_load_strategy_evolver()` or import `StrategyEvolver` from this module; the
implementation will be loaded on demand.
"""

StrategyEvolver = None

def _load_strategy_evolver():
	global StrategyEvolver
	if StrategyEvolver is None:
		from learning.strategy_evolver import StrategyEvolver as _SE

		StrategyEvolver = _SE
	return StrategyEvolver

__all__ = ["StrategyEvolver", "_load_strategy_evolver"]

