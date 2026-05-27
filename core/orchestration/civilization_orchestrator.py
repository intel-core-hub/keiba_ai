import threading
import time
from datetime import datetime

from core.adaptation.auto_evolver import AutoEvolver
from core.alignment.governance_engine import GovernanceEngine
from core.alert_manager import AlertManager
from core.audit_logger import AuditLogger
from core.causal_engine import CausalEngine
from core.civilization_memory import CivilizationMemory
from core.evolution.diagnosis_engine import DiagnosisEngine
from core.evolution.evolution_engine import EvolutionEngine
from core.evolution.global_fitness import GlobalFitness
from core.future.future_engine import FutureEngine
from core.self_modifier import SelfModifier
from core.survival.survival_policy import SurvivalPolicy
from core.world.world_model import WorldModel
from infrastructure.database import SurvivalDatabase


class CivilizationOrchestrator:
    """Civilization-level coordination core."""

    def __init__(self):
        self.memory = CivilizationMemory()
        self.world_model = WorldModel()
        self.future_engine = FutureEngine(memory=self.memory)
        self.survival_policy = SurvivalPolicy()
        self.global_fitness = GlobalFitness()
        self.governance_engine = GovernanceEngine()
        self.diagnosis_engine = DiagnosisEngine()
        self.evolution_engine = EvolutionEngine()
        self.auto_evolver = AutoEvolver()
        self.self_modifier = SelfModifier()
        self.causal_engine = CausalEngine()
        self.alerts = AlertManager()
        self.audit = AuditLogger()
        self.db = SurvivalDatabase()

        self.running = False
        self.cycle_count = 0
        self.last_cycle = None
        self.current_regime = "UNKNOWN"
        self.current_strategy = "OBSERVE"
        self.global_survival_score = 0.0
        self.last_governance_result = None
        self.last_evolution_decision = None
        self.last_strategy_proposal = None

        self.emergency_mode = False
        self.collapse_detected = False
        self.lockdown_mode = False

        self.cycle_interval = 10
        self.max_cycles = 1000000

    def start(self):
        self.running = True
        self.audit.log(
            category="ORCHESTRATOR",
            action="START",
            severity="INFO",
            metadata={"timestamp": datetime.utcnow().isoformat()},
        )

        while self.running:
            try:
                self.run_cycle()
                time.sleep(self.cycle_interval)
            except Exception as exc:
                self.alerts.emit(
                    level="CRITICAL",
                    title="ORCHESTRATOR FAILURE",
                    message=str(exc),
                )
                self.audit.log(
                    category="ORCHESTRATOR",
                    action="CRASH",
                    severity="CRITICAL",
                    metadata={"error": str(exc)},
                )

    def stop(self):
        self.running = False
        self.audit.log(
            category="ORCHESTRATOR",
            action="STOP",
            severity="WARNING",
            metadata={"cycle": self.cycle_count},
        )

    def run_cycle(self):
        self.cycle_count += 1
        self.last_cycle = datetime.utcnow().isoformat()

        world_state = self.observe_world()
        futures = self.future_engine.generate_futures(current_world=world_state, depth=3)
        best_future = self.survival_policy.select_best_future(futures)

        proposed_strategy = self.propose_strategy(best_future)
        evolution_metrics = self.build_evolution_metrics(world_state, best_future)

        governance_result = self.governance_engine.review_transition(
            action={"name": proposed_strategy, "type": "STRATEGY_CHANGE"},
            resources=world_state,
            self_modification={
                "strategy": proposed_strategy,
                "fitness": evolution_metrics["fitness"],
                "scenario": best_future.get("scenario", {}) if best_future else {},
            },
        )
        self.last_governance_result = governance_result

        if governance_result.kill_switch:
            self.emergency_mode = True
            self.lockdown_mode = True

        diagnosis = self.diagnosis_engine.diagnose(evolution_metrics)
        evolution_decision = self.evolution_engine.decide(
            diagnosis=diagnosis,
            current_fitness=evolution_metrics["fitness"],
            previous_fitness=self.global_survival_score,
            governance_result=governance_result,
        )
        self.last_evolution_decision = evolution_decision
        self.last_strategy_proposal = proposed_strategy

        if governance_result.approved:
            self.apply_strategy(proposed_strategy, governance_result, evolution_decision)

            self.evolution_engine.apply_decision(
                decision=evolution_decision,
                payload={
                    "governance": governance_result,
                    "audit": self.audit,
                    "memory": self.memory
                }
            )

            if best_future:
                self.self_modifier.evolve(
                    scenario=best_future.get("scenario", {}),
                    iterations=10,
                )
        else:
            self.audit.log(
                category="ORCHESTRATION",
                action="STRATEGY_REJECTED",
                severity="WARNING",
                metadata={
                    "proposed_strategy": proposed_strategy,
                    "governance": governance_result,
                    "decision": evolution_decision.action,
                },
            )

        self.perform_causal_analysis(world_state)
        self.detect_collapse(world_state)
        self.record_cycle_memory(world_state=world_state, best_future=best_future)
        self.record_governance_cycle(
            world_state=world_state,
            best_future=best_future,
            proposed_strategy=proposed_strategy,
            governance_result=governance_result,
            evolution_decision=evolution_decision,
        )
        self.update_global_score(best_future)
        self.persist_state()

    def observe_world(self):
        state = self.world_model.current_state()
        self.current_regime = state.get("regime", "UNKNOWN")
        return state

    def perform_causal_analysis(self, world_state):
        collapse = world_state.get("collapse_probability", 0.0)
        if collapse > 0.7:
            crash = self.causal_engine.register_event(
                event_type="COLLAPSE_RISK",
                severity=collapse,
            )
            stress = self.causal_engine.register_event(
                event_type="SYSTEM_STRESS",
                severity=world_state.get("stress_index", 0.0),
            )
            self.causal_engine.link_events(stress, crash, confidence=0.87)

    def propose_strategy(self, best_future):
        if not best_future:
            return "SURVIVE"

        score = float(best_future.get("evaluation", {}).get("policy_score", 0.0))
        if score > 0.8:
            return "CONTROLLED_EXPANSION"
        if score > 0.6:
            return "STABILIZE"
        return "DEFENSIVE_SURVIVAL"

    def apply_strategy(self, proposed_strategy, governance_result, evolution_decision):
        previous_strategy = self.current_strategy
        self.current_strategy = proposed_strategy

        if previous_strategy != proposed_strategy:
            self.audit.log(
                category="ORCHESTRATION",
                action="STRATEGY_APPROVED",
                severity="INFO",
                metadata={
                    "previous_strategy": previous_strategy,
                    "current_strategy": proposed_strategy,
                    "governance": governance_result,
                    "decision": evolution_decision.action,
                },
            )

    def build_evolution_metrics(self, world_state, best_future):
        policy_score = 0.0
        if best_future:
            policy_score = float(best_future.get("evaluation", {}).get("policy_score", 0.0))

        metrics = {
            "profit": policy_score,
            "drawdown": float(world_state.get("collapse_probability", 0.0)),
            "stability": max(0.0, 1.0 - float(world_state.get("stress_index", 0.0))),
            "survival": float(self.global_survival_score),
            "drift_detected": bool(world_state.get("drift_detected", False)),
            "overfit_score": max(0.0, 1.0 - policy_score),
        }
        metrics["fitness"] = self.global_fitness.compute(metrics)
        return metrics

    def record_governance_cycle(
        self,
        world_state,
        best_future,
        proposed_strategy,
        governance_result,
        evolution_decision,
    ):
        self.audit.log(
            category="ORCHESTRATION",
            action="GOVERNANCE_CYCLE",
            severity="INFO",
            metadata={
                "regime": self.current_regime,
                "proposed_strategy": proposed_strategy,
                "approved": governance_result.approved,
                "kill_switch": governance_result.kill_switch,
                "diagnosis": evolution_decision.diagnosis,
                "decision": evolution_decision.action,
            },
        )

        self.memory.record_event(
            category="GOVERNANCE",
            title="Cycle Governance",
            content=(
                f"strategy={proposed_strategy}, "
                f"diagnosis={evolution_decision.diagnosis}, "
                f"decision={evolution_decision.action}"
            ),
            severity=world_state.get("stress_index", 0.0),
            tags=["governance", "evolution", proposed_strategy],
        )

    def record_cycle_memory(self, world_state, best_future):
        self.memory.record_event(
            category="ORCHESTRATION",
            title="Civilization Cycle",
            content=f"regime={self.current_regime}, strategy={self.current_strategy}",
            severity=world_state.get("stress_index", 0.0),
            tags=["cycle", "strategy", self.current_strategy],
        )

        if best_future:
            policy_score = best_future.get("evaluation", {}).get("policy_score", 0.0)
            self.memory.record_success_pattern(
                strategy=self.current_strategy,
                result=f"policy score={policy_score}",
                confidence=policy_score,
                tags=["policy", "future"],
            )

    def update_global_score(self, best_future):
        if not best_future:
            self.global_survival_score = 0.0
            return

        self.global_survival_score = float(best_future.get("evaluation", {}).get("policy_score", 0.0))

    def persist_state(self):
        payload = {
            "timestamp": self.last_cycle,
            "cycle": self.cycle_count,
            "regime": self.current_regime,
            "strategy": self.current_strategy,
            "survival_score": self.global_survival_score,
            "emergency_mode": self.emergency_mode,
            "collapse_detected": self.collapse_detected,
            "lockdown_mode": self.lockdown_mode,
            "governance": self.last_governance_result,
            "evolution": getattr(self.last_evolution_decision, "action", None),
        }

        self.db.save_snapshot(state_type="CIVILIZATION_STATE", payload=payload)
        self.audit.log(
            category="ORCHESTRATOR",
            action="PERSIST",
            severity="INFO",
            metadata=payload,
        )

    def detect_collapse(self, world_state):
        collapse = world_state.get("collapse_probability", 0.0)
        if collapse > 0.85:
            self.collapse_detected = True
            self.emergency_mode = True
            self.lockdown_mode = True
            self.alerts.emit(
                level="CRITICAL",
                title="CIVILIZATION COLLAPSE",
                message="collapse threshold exceeded",
            )
            self.memory.record_collapse(
                cause="systemic instability",
                impact="civilization risk spike",
                recovery="lockdown survival mode",
                tags=["collapse", "emergency"],
            )

    def diagnostics(self):
        return {
            "running": self.running,
            "cycle_count": self.cycle_count,
            "last_cycle": self.last_cycle,
            "regime": self.current_regime,
            "strategy": self.current_strategy,
            "survival_score": self.global_survival_score,
            "emergency_mode": self.emergency_mode,
            "collapse_detected": self.collapse_detected,
            "lockdown_mode": self.lockdown_mode,
            "governance": self.last_governance_result,
            "evolution": getattr(self.last_evolution_decision, "action", None),
        }

    def start_async(self):
        thread = threading.Thread(target=self.start, daemon=True)
        thread.start()
        return thread


if __name__ == "__main__":
    orchestrator = CivilizationOrchestrator()
    for _ in range(3):
        orchestrator.run_cycle()
        print(orchestrator.diagnostics())
