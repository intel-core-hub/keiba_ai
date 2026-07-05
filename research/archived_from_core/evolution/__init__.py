try:
	from core.evolution.diagnosis_engine import DiagnosisEngine
	from core.evolution.evolution_engine import EvolutionEngine
	from core.evolution.global_fitness import GlobalFitness
except Exception:
	DiagnosisEngine = None
	EvolutionEngine = None
	GlobalFitness = None
