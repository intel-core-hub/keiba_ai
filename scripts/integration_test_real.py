"""Run a guarded integration test using real Predictor and IPAT client if available.

This script will abort early if required real components or trained model are missing.
"""
import asyncio
import os
import json
from core.audit_hash_log import ImmutableAuditLog
from core.key_manager import KeyManager
from core.circuit_breaker import CircuitBreaker
from core.low_latency_execution import LowLatencyExecutionEngine


async def main():
    # check for trained predictor model
    model_path = os.path.join("models", "predictor.pkl")
    if not os.path.exists(model_path):
        print("No trained predictor model found at models/predictor.pkl; aborting integration test.")
        return

    # Attempt to import real components
    try:
        from core.predictor import Predictor
        from infrastructure.ipat_client import IPATClient
        from core.risk_manager import RiskManager
    except Exception as e:
        print("Required real components not present: ", e)
        return

    # build engine
    audit = ImmutableAuditLog(os.path.join("logs", "audit_integration.jsonl"))
    # attach latest key if present
    km = KeyManager()
    pub = km.get_public_pem()
    if pub:
        # enable signing using that key's private is not available here; we just record pub
        pass

    predictor = Predictor()
    risk_manager = RiskManager()
    ipat = IPATClient()
    cb = CircuitBreaker()
    engine = LowLatencyExecutionEngine(predictor, risk_manager, ipat, audit_log=audit, circuit_breaker=cb)

    # run a single safe execution with timeout
    try:
        await engine.execute_critical_path("REAL-INTEG-TEST-1", timeout_sec=2.0)
        print("Integration run completed (check logs/audit_integration.jsonl)")
    except Exception as e:
        print("Integration run failed:", e)


if __name__ == "__main__":
    asyncio.run(main())
