from typing import Optional, Dict
try:
    import pandas as pd
except Exception:
    pd = None
from .regime_detector import rule_based_regime, ClusterRegimeDetector


class RegimeClassifier:
    """Wrapper that provides a predict method using either rule-based or cluster-based detection.

    Usage:
      clf = RegimeClassifier(mode='rules')
      clf.predict(metrics_dict)

    or fit cluster mode:
      clf = RegimeClassifier(mode='cluster')
      clf.fit(metrics_df)
      clf.predict(metrics_row)
    """

    def __init__(self, mode: str = "rules", n_clusters: int = 4):
        assert mode in ("rules", "cluster")
        self.mode = mode
        self.cluster_detector: Optional[ClusterRegimeDetector] = None
        self.n_clusters = n_clusters

    def fit(self, metrics_df: pd.DataFrame):
        if self.mode != "cluster":
            raise RuntimeError("fit is only valid in cluster mode")
        self.cluster_detector = ClusterRegimeDetector(n_clusters=self.n_clusters)
        self.cluster_detector.fit(metrics_df)
        # user should map clusters to meaningful labels externally
        return self

    def predict(self, metrics: Dict) -> str:
        if self.mode == "rules":
            return rule_based_regime(metrics)
        # cluster mode: expect a 1-row DataFrame-like
        if self.cluster_detector is None:
            raise RuntimeError("ClusterRegimeDetector not fitted")
        df = pd.DataFrame([metrics])
        cluster_id = int(self.cluster_detector.predict(df)[0])
        # default label is cluster_{id}
        return f"cluster_{cluster_id}"
