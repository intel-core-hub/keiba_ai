# learning/brier_score.py

from collections import deque
import numpy as np


class BrierMonitor:
    """
    確率品質監視システム

    目的:
    - calibration drift 検知
    - recent deterioration 検知
    - odds帯崩壊検知

    ROIではなく
    probability quality を監視する
    """

    def __init__(self, window_size=200):

        self.window_size = window_size

        # 全履歴
        self.probs = deque(maxlen=5000)
        self.hits = deque(maxlen=5000)

        # recent監視
        self.recent_probs = deque(
            maxlen=window_size
        )
        self.recent_hits = deque(
            maxlen=window_size
        )

        # odds bucket
        self.bucket_data = {
            "low": [],
            "mid": [],
            "high": [],
        }

    # =========================================
    # 記録
    # =========================================

    def record(
        self,
        probability,
        hit,
        odds=None,
    ):

        self.probs.append(probability)
        self.hits.append(hit)

        self.recent_probs.append(probability)
        self.recent_hits.append(hit)

        # odds bucket
        if odds is not None:

            if odds < 5:
                self.bucket_data["low"].append(
                    (probability, hit)
                )

            elif odds < 15:
                self.bucket_data["mid"].append(
                    (probability, hit)
                )

            else:
                self.bucket_data["high"].append(
                    (probability, hit)
                )

    # =========================================
    # Brier Score
    # =========================================

    def brier_score(self, probs, hits):

        if len(probs) == 0:
            return None

        probs = np.array(probs)
        hits = np.array(hits)

        return float(
            np.mean((probs - hits) ** 2)
        )

    # =========================================
    # Recent
    # =========================================

    def recent_brier(self):

        return self.brier_score(
            self.recent_probs,
            self.recent_hits,
        )

    def current_brier(self):
        return self.recent_brier()

    # =========================================
    # Long-term
    # =========================================

    def overall_brier(self):

        return self.brier_score(
            self.probs,
            self.hits,
        )

    # =========================================
    # Drift Detection
    # =========================================

    def drift_detected(self):

        if len(self.probs) < 300:
            return False

        recent = self.recent_brier()
        overall = self.overall_brier()

        if recent is None or overall is None:
            return False

        # 15%以上悪化
        return recent > overall * 1.15

    # =========================================
    # Odds Bucket Analysis
    # =========================================

    def bucket_report(self):

        report = {}

        for bucket, values in self.bucket_data.items():

            if len(values) < 20:
                report[bucket] = None
                continue

            probs = [v[0] for v in values]
            hits = [v[1] for v in values]

            report[bucket] = round(
                self.brier_score(probs, hits),
                4,
            )

        return report

    # =========================================
    # Status
    # =========================================

    def status(self):

        return {
            "recent_brier": self.recent_brier(),
            "overall_brier": self.overall_brier(),
            "drift_detected": self.drift_detected(),
            "bucket_report": self.bucket_report(),
            "sample_size": len(self.probs),
        }