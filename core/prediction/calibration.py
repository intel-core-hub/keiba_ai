import hashlib
import json
import pickle
from pathlib import Path

import numpy as np


class ProbabilityCalibrator:

    def __init__(self, shrink=0.95, min_prob=0.01, max_prob=0.95):

        self.shrink = shrink
        self.min_prob = min_prob
        self.max_prob = max_prob

        self.bin_edges = None
        self.bin_factors = None

    # -----------------------------

    def _safe_clip(self, prob):
        return max(self.min_prob, min(prob, self.max_prob))

    # -----------------------------
    # 推論時キャリブレーション
    # -----------------------------
    def calibrate(self, prob: float):

        prob *= self.shrink

        if self.bin_edges is not None:

            idx = np.searchsorted(
                self.bin_edges, prob, side="right"
            ) - 1

            idx = np.clip(idx, 0, len(self.bin_factors) - 1)

            factor = np.clip(
                self.bin_factors[idx],
                0.7,
                1.3,
            )

            prob *= factor

        return self._safe_clip(prob)

    # -----------------------------
    # ログ学習
    # -----------------------------
    def fit_from_logs(self, probs, hits, bins=10):

        probs = np.array(probs) * self.shrink
        hits = np.array(hits)

        self.bin_edges = np.linspace(0, 1, bins + 1)
        self.bin_factors = []

        for i in range(bins):

            mask = (
                (probs >= self.bin_edges[i]) &
                (probs < self.bin_edges[i + 1])
            )

            if mask.sum() < 10:
                self.bin_factors.append(1.0)
                continue

            predicted = probs[mask].mean()
            actual = hits[mask].mean()

            if predicted == 0:
                self.bin_factors.append(1.0)
            else:
                self.bin_factors.append(actual / predicted)

        self.bin_factors = np.array(self.bin_factors)

    def to_state(self):
        return {
            "shrink": float(self.shrink),
            "min_prob": float(self.min_prob),
            "max_prob": float(self.max_prob),
            "bin_edges": self.bin_edges.tolist() if self.bin_edges is not None else None,
            "bin_factors": self.bin_factors.tolist() if self.bin_factors is not None else None,
        }

    @classmethod
    def from_state(cls, state):
        calibrator = cls(
            shrink=float(state.get("shrink", 0.95)),
            min_prob=float(state.get("min_prob", 0.01)),
            max_prob=float(state.get("max_prob", 0.95)),
        )
        if state.get("bin_edges") is not None and state.get("bin_factors") is not None:
            calibrator.bin_edges = np.array(state["bin_edges"], dtype=float)
            calibrator.bin_factors = np.array(state["bin_factors"], dtype=float)
        return calibrator

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        payload = self.to_state()
        with open(tmp_path, "wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_path.replace(path)
        return path

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists() or path.stat().st_size == 0:
            raise FileNotFoundError(str(path))
        with open(path, "rb") as handle:
            payload = pickle.load(handle)
        if isinstance(payload, cls):
            return payload
        if isinstance(payload, dict):
            return cls.from_state(payload)
        raise TypeError(f"Unsupported calibration payload: {type(payload)!r}")

    @classmethod
    def load_json_state(cls, path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_state(payload)

    def state_hash(self, path=None):
        if path is not None:
            path = Path(path)
            if path.exists() and path.stat().st_size > 0:
                return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        payload = json.dumps(self.to_state(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    # -----------------------------
    # Brier Score
    # -----------------------------
    def brier_score(self, probs, hits):

        probs = np.array(probs)
        hits = np.array(hits)

        return np.mean((probs - hits) ** 2)

    # -----------------------------
    # ECE
    # -----------------------------
    def expected_calibration_error(self, probs, hits, bins=10):

        probs = np.clip(np.array(probs, dtype=float), self.min_prob, self.max_prob)
        hits = np.array(hits, dtype=float)

        if len(probs) == 0:
            return 0.0

        edges = np.linspace(0.0, 1.0, bins + 1)
        total = len(probs)
        ece = 0.0

        for start, end in zip(edges[:-1], edges[1:]):

            if end == 1.0:
                mask = (probs >= start) & (probs <= end)
            else:
                mask = (probs >= start) & (probs < end)

            count = int(mask.sum())
            if count == 0:
                continue

            avg_prob = probs[mask].mean()
            avg_hit = hits[mask].mean()

            ece += (count / total) * abs(avg_prob - avg_hit)

        return float(ece)

    # -----------------------------
    # Diagnostics
    # -----------------------------
    def diagnostics(self, probs, hits, bins=10):

        probs = np.clip(np.array(probs, dtype=float), self.min_prob, self.max_prob)
        hits = np.array(hits, dtype=float)

        if len(probs) == 0:
            return {
                "brier": 0.0,
                "ece": 0.0,
                "reliability": 1.0,
                "calibration_gap": 0.0,
                "drift_score": 0.0,
            }

        brier = float(self.brier_score(probs, hits))
        ece = float(self.expected_calibration_error(probs, hits, bins=bins))
        calibration_gap = float(abs(probs.mean() - hits.mean()))

        half = max(1, len(probs) // 2)
        first = probs[:half]
        second = probs[half:]
        if len(second) == 0:
            drift = 0.0
        else:
            drift = float(abs(first.mean() - second.mean()))

        return {
            "brier": round(brier, 6),
            "ece": round(ece, 6),
            "reliability": round(max(0.0, 1.0 - ece), 6),
            "calibration_gap": round(calibration_gap, 6),
            "drift_score": round(drift, 6),
        }
