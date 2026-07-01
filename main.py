from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class Decision:
    race_id: str
    selection: str
    odds: float
    probability: float
    stake: int
    decision: str
    reason: str


class _RiskManager:
    def __init__(self, bankroll: float = 100_000.0):
        self.bankroll = float(bankroll)
        self.peak_bankroll = float(bankroll)

    def status(self) -> dict[str, Any]:
        drawdown = 0.0 if self.peak_bankroll <= 0 else max(0.0, 1.0 - self.bankroll / self.peak_bankroll)
        return {"bankroll": self.bankroll, "drawdown": drawdown}

    def settle(self, profit: float) -> None:
        self.bankroll += float(profit)
        self.peak_bankroll = max(self.peak_bankroll, self.bankroll)


class _Capital:
    def __init__(self, initial_capital: float):
        self.initial_capital = float(initial_capital)
        self.mode = "SHADOW"

    def should_shutdown(self) -> bool:
        return False

    def diagnostics(self) -> dict[str, Any]:
        return {"mode": self.mode, "drawdown": 0.0, "survival_score": 1.0}


class _SelfDestruct:
    destroyed = False


class _Reliability:
    def analyze(self) -> dict[str, Any]:
        return {"expected_calibration_error": None, "max_gap": None}


class _RegimeDetector:
    def status(self) -> dict[str, Any]:
        return {"regime": "SHADOW"}


class _MetaController:
    def diagnostics(self) -> dict[str, Any]:
        return {"current_state": "research_only"}


class SurvivalOS:
    """Minimal shadow runtime entrypoint.

    This module intentionally excludes research, learning, simulation, dashboard,
    and autonomous orchestration imports from the production import graph.
    """

    def __init__(self, bankroll: float = 100_000.0):
        self.risk_manager = _RiskManager(bankroll)
        self.capital = _Capital(self.risk_manager.bankroll)
        self.self_destruct = _SelfDestruct()
        self.reliability = _Reliability()
        self.regime_detector = _RegimeDetector()
        self.meta_controller = _MetaController()
        self.decisions: list[Decision] = []

    def process_race(self, race_id: str, candidates: Iterable[dict[str, Any]]) -> list[Decision]:
        decisions: list[Decision] = []
        for candidate in candidates:
            decision = self._evaluate_candidate(race_id, candidate)
            if decision.decision == "BET":
                decisions.append(decision)
        self.decisions.extend(decisions)
        return decisions

    def _evaluate_candidate(self, race_id: str, candidate: dict[str, Any]) -> Decision:
        selection = str(candidate.get("selection", "UNKNOWN"))
        odds = float(candidate.get("odds") or 0.0)
        features = candidate.get("features") or {}
        probability = float(features.get("rank_score", 0.0)) if isinstance(features, dict) else 0.0

        if odds <= 1.0:
            return Decision(race_id, selection, odds, probability, 0, "NO_BET", "invalid_odds")

        implied_probability = 1.0 / odds
        edge = probability - implied_probability
        if edge <= 0.05:
            return Decision(race_id, selection, odds, probability, 0, "NO_BET", "insufficient_edge")

        stake = min(100, int(max(0.0, self.risk_manager.bankroll * 0.001)))
        return Decision(race_id, selection, odds, probability, stake, "BET", "shadow_edge")

    def settle_race(self, decisions: Iterable[Decision], winners: Iterable[str]) -> None:
        winner_set = set(winners)
        for decision in decisions:
            if decision.decision != "BET":
                continue
            if decision.selection in winner_set:
                self.risk_manager.settle(decision.stake * (decision.odds - 1.0))
            else:
                self.risk_manager.settle(-decision.stake)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "deployment_status": "Research Only / Shadow Trading",
            "bankroll": self.risk_manager.bankroll,
            "decisions": len(self.decisions),
            "capital": self.capital.diagnostics(),
            "regime": self.regime_detector.status(),
            "meta": self.meta_controller.diagnostics(),
        }

    def monte_carlo_check(self) -> dict[str, str]:
        return {"status": "offline_only"}


if __name__ == "__main__":
    system = SurvivalOS()
    sample_race = [
        {"selection": "Horse_A", "odds": 4.5, "features": {"rank_score": 0.82}},
        {"selection": "Horse_B", "odds": 12.0, "features": {"rank_score": 0.55}},
    ]
    sample_decisions = system.process_race("SHADOW_SAMPLE", sample_race)
    system.settle_race(sample_decisions, ["Horse_A"])
    print(system.diagnostics())
