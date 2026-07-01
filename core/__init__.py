"""Production-safe core package marker.

Import concrete runtime components from their owning modules, for example:
``core.low_latency_execution`` or ``core.betting.decision_engine``.
"""

__all__: list[str] = []
