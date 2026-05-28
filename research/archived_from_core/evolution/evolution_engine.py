from dataclasses import dataclass
from typing import Any, Optional

from core.evolution.model_registry import ModelRegistry


@dataclass
class EvolutionDecision:
    action: str
    reason: str
    risk: float = 0.0
    target: Optional[str] = None
    diagnosis: Optional[str] = None


class EvolutionEngine:
    def __init__(self, registry: Optional[ModelRegistry] = None, fitness: Any | None = None, governance: Any | None = None, settings_path: str = "config/settings.yaml"):
        self.registry = registry or ModelRegistry()
        self.fitness = fitness
        self.governance = governance
        self.settings_path = settings_path

    def _get_limits(self) -> dict:
        import yaml
        from pathlib import Path
        path = Path(self.settings_path)
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                return data.get("civilization_limits", {})
        return {}

    def decide(self, diagnosis: str, current_fitness: Optional[float] = None, previous_fitness: Optional[float] = None, governance_result: Any | None = None) -> EvolutionDecision:
        # If governance explicitly rejects, block action
        if governance_result is not None:
            approved = getattr(governance_result, "approved", None)
            if approved is None and isinstance(governance_result, dict):
                approved = governance_result.get("approved", False)
            if approved is False:
                return EvolutionDecision(action="BLOCKED", reason="governance_rejected", risk=0.0, diagnosis=diagnosis)

        # Compute risk as fitness degradation
        risk = 0.0
        limits = self._get_limits()
        max_risk_jump = limits.get("max_risk_jump", 0.15)

        if previous_fitness is not None and current_fitness is not None:
            risk = max(0.0, previous_fitness - current_fitness)
            if risk > max_risk_jump:
                # Halt evolution immediately due to extreme risk
                return EvolutionDecision(action="BLOCKED", reason="limit_max_risk_jump_exceeded", risk=risk, diagnosis=diagnosis)
            
            if current_fitness < previous_fitness:
                latest = self.registry.latest_checkpoint()
                return EvolutionDecision(action="ROLLBACK", reason="fitness_degradation", risk=risk, target=str(latest) if latest else None, diagnosis=diagnosis)

        if diagnosis == "OVERFITTING":
            return EvolutionDecision(action="RETRAIN", reason="overfitting_detected", risk=risk, target="auto_retrainer", diagnosis=diagnosis)

        if diagnosis == "REGIME_SHIFT":
            return EvolutionDecision(action="EVOLVE_SETTINGS", reason="regime_shift", risk=risk, target="auto_evolver", diagnosis=diagnosis)

        if diagnosis == "RISK_TOO_HIGH":
            return EvolutionDecision(action="HOLD_AND_OBSERVE", reason="risk_too_high", risk=risk, target="risk_manager", diagnosis=diagnosis)

        return EvolutionDecision(action="NOOP", reason="stable", risk=risk, diagnosis=diagnosis)

    def apply_decision(self, decision: EvolutionDecision, payload: Optional[dict] = None) -> dict:
        payload = payload or {}
        result = {"action": decision.action, "status": "skipped"}

        if decision.action == "ROLLBACK":
            checkpoint = decision.target
            try:
                rolled = self.registry.rollback(checkpoint)
                result.update({"status": "ok" if rolled else "no_checkpoint", "rolled_to": str(rolled) if rolled else None})
            except Exception as e:
                result.update({"status": "error", "error": str(e)})
            return result

        if decision.action == "RETRAIN":
            try:
                from core.adaptation.auto_retrainer import AutoRetrainer

                retrainer = AutoRetrainer()
                res = retrainer.retrain()
                result.update({"status": "ok", "result": res})
            except Exception as e:
                result.update({"status": "error", "error": str(e)})
            return result

        if decision.action == "EVOLVE_SETTINGS":
            try:
                from core.adaptation.auto_evolver import AutoEvolver

                evolver = AutoEvolver()
                res = evolver.evolve(governance_result=payload.get("governance"), audit_logger=payload.get("audit"), memory=payload.get("memory"))
                result.update({"status": "ok", "result": res})
            except Exception as e:
                result.update({"status": "error", "error": str(e)})
            return result

        # HOLD_AND_OBSERVE, NOOP, BLOCKED
        result.update({"status": "noop"})
        return result