import json
import os
import pytest


LATENCY_CONFIG = ".ci_latency.json"


@pytest.mark.skipif(not os.path.exists(LATENCY_CONFIG), reason="no latency config")
def test_latency_within_thresholds():
    with open(LATENCY_CONFIG, "r", encoding="utf8") as f:
        cfg = json.load(f)
    # Expected keys: p50, p95, p99 measured in ms
    thresholds = {"p50": 20, "p95": 50, "p99": 100}
    for k, thresh in thresholds.items():
        measured = cfg.get(k)
        assert measured is not None, f"missing {k} in {LATENCY_CONFIG}"
        assert measured <= thresh, f"{k} {measured}ms exceeds threshold {thresh}ms"
