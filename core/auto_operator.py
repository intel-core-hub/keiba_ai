from core.regime_detector import RegimeDetector


def _load_experimental_engines():
    try:
        from core.evolution.diagnosis_engine import DiagnosisEngine
        from core.evolution.evolution_engine import EvolutionEngine
        from core.evolution.global_fitness import GlobalFitness
        return DiagnosisEngine, EvolutionEngine, GlobalFitness
    except Exception:
        return None, None, None


class AutoOperator:
    def __init__(self, risk_manager, stop_drawdown: float = 0.35):
        self.risk_manager = risk_manager
        self.stop_drawdown = stop_drawdown
        self.regime_detector = RegimeDetector()
        diagnosis_cls, evolution_cls, fitness_cls = _load_experimental_engines()
        self.global_fitness = fitness_cls() if fitness_cls is not None else None
        self.diagnosis_engine = diagnosis_cls() if diagnosis_cls is not None else None
        self.evolution_engine = evolution_cls() if evolution_cls is not None else None
        self.running = True

    def emergency_stop(self) -> bool:
        drawdown = 0.0
        if hasattr(self.risk_manager, "drawdown"):
            drawdown = float(self.risk_manager.drawdown())
        return drawdown >= self.stop_drawdown

    def update_mode(self) -> str:
        drawdown = 0.0
        if hasattr(self.risk_manager, "drawdown"):
            drawdown = float(self.risk_manager.drawdown())

        if drawdown >= self.stop_drawdown:
            return "HALT"
        if drawdown >= self.stop_drawdown * 0.7:
            return "DEFENSIVE"
        return "NORMAL"

    def status(self):
        return {
            "running": self.running,
            "drawdown": float(self.risk_manager.drawdown()) if hasattr(self.risk_manager, "drawdown") else 0.0,
            "bankroll": getattr(self.risk_manager, "bankroll", None),
        }

    def assess(self, stats):
        fitness = self.global_fitness.compute(stats) if self.global_fitness is not None else None
        diagnosis = self.diagnosis_engine.diagnose(stats) if self.diagnosis_engine is not None else None
        evolution = self.evolution_engine.evolve(diagnosis) if self.evolution_engine is not None else None

        return {
            "fitness": fitness,
            "diagnosis": diagnosis,
            "evolution": evolution,
        }
