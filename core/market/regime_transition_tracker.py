from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


@dataclass
class TransitionRecord:
    source: str
    target: str
    count: int = 0


class RegimeTransitionTracker:
    """Track regime-to-regime transitions using plain counts and probabilities."""

    def __init__(self):
        self._counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._sequence: List[str] = []

    def record(self, regime: str):
        regime = str(regime or "unknown")
        if self._sequence:
            previous = self._sequence[-1]
            self._counts[previous][regime] += 1
        self._sequence.append(regime)

    def record_many(self, regimes: Sequence[str]):
        for regime in regimes:
            self.record(regime)

    def transition_matrix(self) -> pd.DataFrame:
        labels = list(dict.fromkeys(self._sequence))
        if not labels:
            return pd.DataFrame()
        frame = pd.DataFrame(0, index=labels, columns=labels, dtype=int)
        for source, targets in self._counts.items():
            for target, count in targets.items():
                frame.loc[source, target] = int(count)
        return frame

    def transition_graph(self) -> pd.DataFrame:
        rows = []
        for source, targets in self._counts.items():
            total = sum(targets.values())
            if total <= 0:
                continue
            for target, count in targets.items():
                rows.append({
                    "source": source,
                    "target": target,
                    "count": int(count),
                    "probability": float(count / total),
                })
        return pd.DataFrame.from_records(rows).sort_values(["source", "count"], ascending=[True, False]) if rows else pd.DataFrame(columns=["source", "target", "count", "probability"])

    def top_transitions(self, min_count: int = 1) -> pd.DataFrame:
        graph = self.transition_graph()
        if len(graph) == 0:
            return graph
        return graph.loc[graph["count"] >= int(min_count)].reset_index(drop=True)

    def to_dot(self) -> str:
        lines = ["digraph regime_transitions {"]
        graph = self.transition_graph()
        for _, row in graph.iterrows():
            lines.append(f'  "{row["source"]}" -> "{row["target"]}" [label="{int(row["count"])}"];')
        lines.append("}")
        return "\n".join(lines)

    def summary(self) -> Dict[str, object]:
        return {
            "n_regimes": len(set(self._sequence)),
            "n_transitions": int(sum(sum(targets.values()) for targets in self._counts.values())),
            "transition_matrix": self.transition_matrix(),
            "transition_graph": self.transition_graph(),
        }
