"""Safe runner that builds IPAT client from env and runs one critical execution.

Requires env vars for real run: IPAT_API_URL, IPAT_API_KEY. Otherwise runs with mock.
"""
import asyncio
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.ipat_adapter import build_from_env
from core.audit_hash_log import ImmutableAuditLog
from core.circuit_breaker import CircuitBreaker
from core.low_latency_execution import LowLatencyExecutionEngine
from core.key_manager import KeyManager


async def main():
    ipat = build_from_env()
    audit = ImmutableAuditLog(os.path.join("logs","audit_safe_run.jsonl"))
    # If key material exists, enable signing without assuming filesystem-backed storage.
    km = KeyManager()
    private_pem = km.load_private_pem()
    if private_pem:
        try:
            audit.enable_ecdsa_from_private_pem(private_pem, include_public_in_entry=True)
        except Exception:
            pass

    # use real predictor/risk_manager if available else abort
    try:
        from core.predictor import Predictor
        from core.risk_manager import RiskManager
    except Exception as e:
        print("Real predictor/risk_manager not available; aborting safe-run.")
        return

    predictor = Predictor()
    risk_manager = RiskManager()
    cb = CircuitBreaker()
    engine = LowLatencyExecutionEngine(predictor, risk_manager, ipat, audit_log=audit, circuit_breaker=cb)

    await engine.execute_critical_path("SAFE-RUN-1", timeout_sec=2.0)
    print("Safe run complete; check logs/audit_safe_run.jsonl")


if __name__ == "__main__":
    asyncio.run(main())
