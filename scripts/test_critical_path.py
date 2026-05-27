import asyncio
import time
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib.util
import types

# Load modules directly by path to avoid importing heavy top-level package initializers
repo_root = Path(__file__).resolve().parents[1]
core_path = repo_root / "core"
ll_path = core_path / "low_latency_execution.py"
cb_path = core_path / "circuit_breaker.py"

# Create a lightweight fake 'core' package module so relative imports inside
# core submodules work when loaded from file.
core_pkg = types.ModuleType("core")
core_pkg.__path__ = [str(core_path)]
import sys as _sys
_sys.modules["core"] = core_pkg

spec = importlib.util.spec_from_file_location("core.low_latency_execution", str(ll_path))
lowlat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lowlat)

spec2 = importlib.util.spec_from_file_location("core.circuit_breaker", str(cb_path))
cbmod = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(cbmod)

LowLatencyExecutionEngine = lowlat.LowLatencyExecutionEngine
CircuitBreaker = cbmod.CircuitBreaker


class SlowPredictor:
    def __init__(self, delay=0.2):
        self.delay = delay
        self.trained = True

    def predict_raw(self, features):
        # blocking sleep to simulate heavy CPU work
        time.sleep(self.delay)
        return [0.5 for _ in (features or [0])]


class SlowIPAT:
    async def fetch_live_odds_async(self, race_id):
        await asyncio.sleep(0)
        # include provider_timestamp as current time
        return {"precomputed_feature_vector": [{"rank_score": 0.5}], "odds": [5.0], "provider_timestamp": time.time()}

    async def place_bet_async(self, race_id, allocations):
        await asyncio.sleep(0)
        return {"status": "ok"}


async def run_test():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=2.0)
    predictor = SlowPredictor(delay=0.3)
    ipat = SlowIPAT()
    engine = LowLatencyExecutionEngine(predictor=predictor, risk_manager=type("R", (), {"calculate_sizing": lambda self, p, o: {"should_bet": False}})(), ipat_client=ipat, circuit_breaker=cb, staleness_threshold=1.0)

    for i in range(4):
        race_id = f"TEST{i}"
        try:
            await engine.execute_critical_path(race_id, timeout_sec=0.1)
        except Exception as e:
            print(f"Run {i} -> Exception: {e}")
        print(f"Circuit open: {cb.is_open()}, failures: {cb.failures}")
        await asyncio.sleep(0.2)

if __name__ == "__main__":
    os.environ["DISABLE_META"] = "1"
    asyncio.run(run_test())
