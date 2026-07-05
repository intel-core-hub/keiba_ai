from core.decision_engine import DecisionEngine
from execution.phase2_loop import Phase2OperationalLoop

def run_race(engine, race_id, candidates):

    return engine.decide_race(race_id, candidates)


def run_race_phase2(loop: Phase2OperationalLoop, race_id, candidates):

    return loop.decide_race(race_id, candidates)
