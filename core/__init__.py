# core/__init__.py

import os
from importlib import import_module

# Prediction modules
from .prediction.predictor import Predictor
from .prediction.regime_detector import RegimeDetector

# Betting modules
from .bet_sizer import BetSizer
from .betting.bankroll_manager import BankrollManager
from .betting.capital_preservation import CapitalPreservation
from .betting.decision_engine import DecisionEngine
from .betting.fund_core import FundCore
from .betting.no_bet_filter import NoBetFilter
from .risk_manager import RiskManager
from .portfolio_allocator import PortfolioAllocator

# Cognition modules

class _NullMetaController:
    def determine_state(self, *args, **kwargs):
        return {"mode": "NORMAL", "reason": "research_disabled"}

# Execution modules
from .execution.bet_executor import BetExecutor

# Security modules
from .security.emergency_shutdown import SelfDestructSystem

__all__ = [
    # Prediction
    "Predictor",
    "RegimeDetector",
    # Betting
    "BetSizer",
    "BankrollManager",
    "CapitalPreservation",
    "DecisionEngine",
    "FundCore",
    "NoBetFilter",
    "PortfolioAllocator",
    "RiskManager",
    # Cognition
    "MetaController",
    # Execution
    "BetExecutor",
    # Security
    "SelfDestructSystem",
]


def __getattr__(name):
    if name != "MetaController":
        raise AttributeError(f"module 'core' has no attribute {name!r}")

    if os.getenv("KEIBA_ENABLE_RESEARCH", "0") == "1":
        module = import_module("core.cognition.meta_controller")
        value = getattr(module, "MetaController")
    else:
        value = _NullMetaController

    globals()[name] = value
    return value
