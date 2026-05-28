import hashlib
import json


def canonical_hash(obj) -> str:
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode("utf8")).hexdigest()


def test_same_snapshot_hash_is_deterministic():
    snap = {
        "feature_hash": "abc",
        "odds_hash": "def",
        "model_hash": "v1",
        "timestamp": 1234567890,
    }
    h1 = canonical_hash(snap)
    h2 = canonical_hash(snap.copy())
    assert h1 == h2


def test_different_snapshot_hashes_differ():
    a = {"x": 1, "y": 2}
    b = {"y": 2, "x": 1, "z": 3}
    assert canonical_hash(a) != canonical_hash(b)
