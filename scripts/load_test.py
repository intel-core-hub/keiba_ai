"""Load/latency test for LowLatencyExecutionEngine.

Usage:
  python -m scripts.load_test [concurrency] [requests_per_worker]

Example:
  python -m scripts.load_test 20 50
"""
import argparse
import asyncio
import os
import sys
import statistics
import time
from time import perf_counter
import importlib.util
import types
from pathlib import Path

# Load core submodules directly by file path to avoid executing heavy core.__init__
repo_root = Path(__file__).resolve().parents[1]
core_path = repo_root / "core"

# Create a minimal 'core' package module so relative imports inside core submodules work
core_pkg = types.ModuleType("core")
core_pkg.__path__ = [str(core_path)]
sys.modules["core"] = core_pkg

def _load_core_mod(name, relpath):
    spec = importlib.util.spec_from_file_location(name, str(core_path / relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

lowlat_mod = _load_core_mod("core.low_latency_execution", "low_latency_execution.py")
ll = lowlat_mod
cb_mod = _load_core_mod("core.circuit_breaker", "circuit_breaker.py")
cbm = cb_mod
audit_mod = _load_core_mod("core.audit_hash_log", "audit_hash_log.py")
audmod = audit_mod

LowLatencyExecutionEngine = ll.LowLatencyExecutionEngine
ImmutableAuditLog = audmod.ImmutableAuditLog
CircuitBreaker = cbm.CircuitBreaker
import json
import csv
import os
import datetime
try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None


def nearest_rank_percentiles(values, ps=(50, 95, 99, 99.9)):
    if not values:
        return {p: None for p in ps}
    ordered = sorted(values)
    n = len(ordered)
    return {
        p: ordered[int(round((p / 100.0) * (n - 1)))]
        for p in ps
    }


def build_ci_latency_payload(latencies, timeout_count, baseline_p99=None):
    if not latencies:
        raise ValueError("no latency samples recorded")
    if timeout_count < 0:
        raise ValueError("timeout_count must be non-negative")
    if timeout_count > len(latencies):
        raise ValueError("timeout_count cannot exceed latency sample count")

    percentiles = nearest_rank_percentiles(latencies)
    payload = {
        "p50": float(percentiles[50]),
        "p95": float(percentiles[95]),
        "p99": float(percentiles[99]),
        "p999": float(percentiles[99.9]),
        "timeout_rate": float(timeout_count / len(latencies)),
    }
    if baseline_p99 is not None:
        payload["baseline_p99"] = float(baseline_p99)
    return payload


def write_ci_latency_payload(path, latencies, timeout_count, baseline_p99=None):
    payload = build_ci_latency_payload(latencies, timeout_count, baseline_p99=baseline_p99)
    output = Path(path)
    if output.parent != Path("."):
        output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return payload


class MockPredictor:
    def predict_raw(self, features):
        # Return a scalar probability for a single selection; keep API compatible
        return 0.2 if features else 0.1


class MockRiskManager:
    def calculate_sizing(self, predicted_probs, odds):
        prob = predicted_probs[0] if isinstance(predicted_probs, (list, tuple)) else predicted_probs
        should = prob > 0.01
        return {"should_bet": should, "allocations": [{"horse": "H1", "amount": 1}]}


class MockIPATClient:
    async def fetch_live_odds_async(self, race_id):
        await asyncio.sleep(0)
        return {
            "timestamp": time.time(),
            "precomputed_feature_vector": [1, 2, 3],
            "odds": [5.0],
            "calibration_state": {"expired": False, "invalid": False},
            "bankroll_state": {"uncertain": False, "stale": False},
        }

    async def place_bet_async(self, race_id, allocations):
        await asyncio.sleep(0)
        return {"status": "ok", "race_id": race_id, "allocations": allocations}


async def worker(engine, worker_id, nreq, latencies, failures):
    for i in range(nreq):
        race_id = f"LOAD-{worker_id}-{i}"
        t0 = perf_counter()
        try:
            await engine.execute_critical_path(race_id, timeout_sec=2.0)
        except Exception:
            failures.append(race_id)
        t1 = perf_counter()
        latencies.append((t1 - t0) * 1000.0)


async def main(concurrency=10, requests_per_worker=10, *, mock_only=False, ci_output=None, baseline_p99=None):
    log_path = os.path.join("logs", "audit_chain.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    audit = ImmutableAuditLog(log_path)
    audit.enable_hmac("loadtest-key")
    cb = CircuitBreaker(failure_threshold=1000, recovery_timeout=60)

    if mock_only:
        predictor = MockPredictor()
        risk_manager = MockRiskManager()
        ipat_client = MockIPATClient()
    else:
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
    failures = []
    tasks = []
    for w in range(concurrency):
        tasks.append(asyncio.create_task(worker(engine, w, requests_per_worker, latencies, failures)))

    start = perf_counter()
    await asyncio.gather(*tasks)
    total = perf_counter() - start

    if latencies:
        n = len(latencies)
        mean = statistics.mean(latencies)
        percentiles = nearest_rank_percentiles(latencies)
        p95 = percentiles[95]
        p99 = percentiles[99]
        p999 = percentiles[99.9]
        timeout_rate = float(len(failures) / n) if n else 0.0
        mx = max(latencies)
        print(f"Requests: {n}")
        print(f"Elapsed total: {total:.3f}s")
        print(f"Mean(ms): {mean:.2f}")
        print(f"P95(ms): {p95:.2f}")
        print(f"P99(ms): {p99:.2f}")
        print(f"P999(ms): {p999:.2f}")
        print(f"Timeout rate: {timeout_rate:.6f}")
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
            'p99_ms': p99,
            'p999_ms': p999,
            'timeout_rate': timeout_rate,
            'timeouts': len(failures),
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

        if ci_output:
            payload = write_ci_latency_payload(ci_output, latencies, len(failures), baseline_p99=baseline_p99)
            print(f"Saved CI latency gate: {ci_output}")
            print(json.dumps(payload, sort_keys=True))
    else:
        print("No latencies recorded")
        if ci_output:
            raise SystemExit(2)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Run a LowLatencyExecutionEngine latency test.")
    parser.add_argument("concurrency", nargs="?", type=int, default=10)
    parser.add_argument("requests_per_worker", nargs="?", type=int, default=10)
    parser.add_argument(
        "--mock-only",
        action="store_true",
        help="Use mock predictor, risk manager, and IPAT client for deterministic CI gating.",
    )
    parser.add_argument(
        "--ci-output",
        help="Write strict .ci_latency.json-compatible metrics to this path.",
    )
    parser.add_argument(
        "--baseline-p99",
        type=float,
        default=None,
        help="Approved previous-release p99 latency to preserve for v2.2 regression checks.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    asyncio.run(
        main(
            args.concurrency,
            args.requests_per_worker,
            mock_only=args.mock_only,
            ci_output=args.ci_output,
            baseline_p99=args.baseline_p99,
        )
    )
