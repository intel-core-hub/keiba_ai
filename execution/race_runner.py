from core.decision_engine import DecisionEngine
from execution.phase2_loop import Phase2OperationalLoop

def run_race(engine, race_id, candidates):

    decisions = engine.decide_race(race_id, candidates)

    for d in decisions:
        print(
            f"BUY {d.selection} "
            f"odds={d.odds} "
            f"bet={d.bet_size}"
        )

    return decisions


def run_race_phase2(loop: Phase2OperationalLoop, race_id, candidates):

    decisions = loop.decide_race(race_id, candidates)

    for d in decisions:
        print(
            f"BUY {d.selection} "
            f"odds={d.odds} "
            f"ev={d.expected_value:.3f} "
            f"unc={d.uncertainty_score:.3f} "
            f"bet={d.bet_size}"
        )

    return decisions