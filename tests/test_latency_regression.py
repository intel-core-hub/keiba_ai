import json
import os
import pytest


LATENCY_CONFIG = ".ci_latency.json"
LATENCY_THRESHOLDS = {
    "p50": 20,
    "p95": 50,
    "p99": 100,
    "p999": 250,
}


def validate_latency_config(path):
    with open(path, "r", encoding="utf8") as f:
        cfg = json.load(f)
    for key, threshold in LATENCY_THRESHOLDS.items():
        measured = cfg.get(key)
        assert measured is not None, f"missing {key} in {path}"
        assert measured <= threshold, f"{key} {measured}ms exceeds threshold {threshold}ms"

    timeout_rate = cfg.get("timeout_rate")
    assert timeout_rate is not None, f"missing timeout_rate in {path}"
    assert timeout_rate == 0, f"timeout_rate {timeout_rate} must be 0"


@pytest.mark.skipif(not os.path.exists(LATENCY_CONFIG), reason="no latency config")
def test_latency_within_thresholds():
    validate_latency_config(LATENCY_CONFIG)


def test_latency_gate_accepts_complete_safe_config(tmp_path):
    path = tmp_path / ".ci_latency.json"
    path.write_text(
        json.dumps({"p50": 10, "p95": 30, "p99": 80, "p999": 150, "timeout_rate": 0}),
        encoding="utf-8",
    )

    validate_latency_config(path)


@pytest.mark.parametrize(
    "payload,match",
    [
        ({"p50": 10, "p95": 30, "p99": 80, "timeout_rate": 0}, "missing p999"),
        ({"p50": 10, "p95": 30, "p99": 80, "p999": 150}, "missing timeout_rate"),
        ({"p50": 10, "p95": 30, "p99": 80, "p999": 251, "timeout_rate": 0}, "p999"),
        ({"p50": 10, "p95": 30, "p99": 80, "p999": 150, "timeout_rate": 0.01}, "timeout_rate"),
    ],
)
def test_latency_gate_rejects_missing_or_unsafe_tail_metrics(tmp_path, payload, match):
    path = tmp_path / ".ci_latency.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AssertionError, match=match):
        validate_latency_config(path)
