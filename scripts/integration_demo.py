"""Integration demo: attempt to use real components if present, else fallback to mocks.

Run with: python -m scripts.integration_demo
"""
import asyncio
import os
import json
from core.low_latency_execution import LowLatencyExecutionEngine
from core.audit_hash_log import ImmutableAuditLog
from core.circuit_breaker import CircuitBreaker


class MockPredictor:
    def predict_raw(self, features):
        return [0.2 for _ in range(len(features))] if features else [0.1]


class MockRiskManager:
    def calculate_sizing(self, predicted_probs, odds):
        prob = predicted_probs[0] if isinstance(predicted_probs, (list, tuple)) else predicted_probs
        should = prob > 0.15
        return {"should_bet": should, "allocations": [{"horse": "H1", "amount": 100}]}


class MockIPATClient:
    async def fetch_live_odds_async(self, race_id):
        await asyncio.sleep(0)
        return {"precomputed_feature_vector": [1, 2, 3], "odds": [5.0]}

    async def place_bet_async(self, race_id, allocations):
        await asyncio.sleep(0)
        return {"status": "ok", "race_id": race_id, "allocations": allocations}


async def main():
    log_path = os.path.join("logs", "audit_chain.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    audit = ImmutableAuditLog(log_path)
    # enable HMAC for demo (in production, provide secure key)
    audit.enable_hmac("demo-secret-key")

    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)

    # Try to import actual implementations; fall back to mocks
    try:
        from core.predictor import Predictor
        predictor = Predictor()
        # require explicit predict_raw method for low-latency path; otherwise fallback
        if not hasattr(predictor, "predict_raw"):
            predictor = MockPredictor()
    except Exception:
        predictor = MockPredictor()

    try:
        from core.risk_manager import RiskManager
        risk_manager = RiskManager()
        if not hasattr(risk_manager, "calculate_sizing"):
            risk_manager = MockRiskManager()
    except Exception:
        risk_manager = MockRiskManager()

    try:
        from infrastructure.ipat_client import IPATClient
        ipat_client = IPATClient()
        if not (hasattr(ipat_client, "fetch_live_odds_async") and hasattr(ipat_client, "place_bet_async")):
            ipat_client = MockIPATClient()
    except Exception:
        ipat_client = MockIPATClient()

    engine = LowLatencyExecutionEngine(predictor, risk_manager, ipat_client, audit_log=audit, circuit_breaker=cb)

    # run a few iterations
    for i in range(3):
        await engine.execute_critical_path(f"RACE-DEMO-{i}", timeout_sec=1.0)
        await asyncio.sleep(0.01)

    # print last line of audit log
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    print("Audit lines:", len(lines))
    if lines:
        print(json.loads(lines[-1]))


if __name__ == "__main__":
    asyncio.run(main())
