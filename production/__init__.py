"""Production boundary for stable, auditable modules.

This package is intentionally declarative. It does not import the full runtime
graph; it only defines the modules that should remain on the production path.
"""

PRODUCTION_MODULES = [
    "core.prediction",
    "core.betting",
    "core.execution",
    "core.market",
    "core.security",
    "core.portfolio_allocator",
    "core.risk_manager",
    "core.replay",
    "dashboard",
    "execution",
    "infrastructure",
    "simulation",
    "validation",
]

PRODUCTION_CRITERIA = [
    "measurable",
    "reproducible",
    "explainable",
    "stable",
    "directly_profitable",
    "auditable",
]
