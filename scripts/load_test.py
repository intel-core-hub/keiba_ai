"""Load/latency test for LowLatencyExecutionEngine.

Usage:
  python -m scripts.load_test [concurrency] [requests_per_worker]

Example:
  python -m scripts.load_test 20 50
"""
import asyncio
import os
import sys
import statistics
from time import perf_counter
from core.low_latency_execution import LowLatencyExecutionEngine
from core.audit_hash_log import ImmutableAuditLog
from core.circuit_breaker import CircuitBreaker
import json
import csv
import os
import datetime
try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None


class MockPredictor:
    def predict_raw(self, features):
        return [0.2 for _ in range(len(features))] if features else [0.1]


class MockRiskManager:
    def calculate_sizing(self, predicted_probs, odds):
        prob = predicted_probs[0] if isinstance(predicted_probs, (list, tuple)) else predicted_probs
        should = prob > 0.01
        return {"should_bet": should, "allocations": [{"horse": "H1", "amount": 1}]}


class MockIPATClient:
    async def fetch_live_odds_async(self, race_id):
        await asyncio.sleep(0)
        return {"precomputed_feature_vector": [1, 2, 3], "odds": [5.0]}

    async def place_bet_async(self, race_id, allocations):
        await asyncio.sleep(0)
        return {"status": "ok", "race_id": race_id, "allocations": allocations}


async def worker(engine, worker_id, nreq, latencies):
    for i in range(nreq):
        race_id = f"LOAD-{worker_id}-{i}"
        t0 = perf_counter()
        await engine.execute_critical_path(race_id, timeout_sec=2.0)
        t1 = perf_counter()
        latencies.append((t1 - t0) * 1000.0)


async def main(concurrency=10, requests_per_worker=10):
    log_path = os.path.join("logs", "audit_chain.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    audit = ImmutableAuditLog(log_path)
    audit.enable_hmac("loadtest-key")
    cb = CircuitBreaker(failure_threshold=1000, recovery_timeout=60)

    # try to use real implementations if present and compatible
    try:
        from core.predictor import Predictor
        predictor = Predictor()
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

    latencies = []
    tasks = []
    for w in range(concurrency):
        tasks.append(asyncio.create_task(worker(engine, w, requests_per_worker, latencies)))

    start = perf_counter()
    await asyncio.gather(*tasks)
    total = perf_counter() - start

    if latencies:
        n = len(latencies)
        mean = statistics.mean(latencies)
        p95 = statistics.quantiles(latencies, n=100)[94]
        mx = max(latencies)
        print(f"Requests: {n}")
        print(f"Elapsed total: {total:.3f}s")
        print(f"Mean(ms): {mean:.2f}")
        print(f"P95(ms): {p95:.2f}")
        print(f"Max(ms): {mx:.2f}")

        # save report
        ts = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        rpt_dir = os.path.join('reports')
        os.makedirs(rpt_dir, exist_ok=True)
        json_path = os.path.join(rpt_dir, f'load_test_{ts}.json')
        csv_path = os.path.join(rpt_dir, f'load_test_{ts}.csv')
        png_path = os.path.join(rpt_dir, f'load_test_{ts}.png')

        summary = {
            'requests': n,
            'elapsed_s': total,
            'mean_ms': mean,
            'p95_ms': p95,
            'max_ms': mx,
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({'summary': summary, 'latencies_ms': latencies}, f)

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['index', 'latency_ms'])
            for i, v in enumerate(latencies):
                writer.writerow([i, v])

        if plt is not None:
            plt.figure(figsize=(8,4))
            plt.plot(sorted(latencies))
            plt.title('Load test latencies (ms)')
            plt.xlabel('sorted request index')
            plt.ylabel('latency (ms)')
            plt.grid(True)
            plt.tight_layout()
            plt.savefig(png_path)

        print(f"Saved report: {json_path}, {csv_path}")
        if plt is not None:
            print(f"Saved plot: {png_path}")
    else:
        print("No latencies recorded")


if __name__ == "__main__":
    c = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    r = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    asyncio.run(main(c, r))
