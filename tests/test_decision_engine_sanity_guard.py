from __future__ import annotations

from core.betting.decision_engine import DecisionEngine


class _Predictor:
    trained = False

    def predict(self, race_id, selection, features, odds=None):
        return 0.12


class _TrainedPredictor(_Predictor):
    trained = True


class _BetSizer:
    def calculate_bet(self, **kwargs):
        return 100


class _Risk:
    bankroll = 10000

    def status(self):
        return {"drawdown": 0.0}

    def can_bet(self):
        return True

    def risk_multiplier(self):
        return 1.0

    def max_bet_size(self):
        return 100

    def drawdown(self):
        return 0.0

    def reset_race_risk(self):
        pass

    def register_bet(self, amount):
        pass


class _Calibrator:
    def calibrate(self, value):
        return float(value)


class _Logger:
    def __init__(self):
        self.records = []

    def log_decision(self, **kwargs):
        self.records.append(kwargs)


def _engine(predictor):
    logger = _Logger()
    engine = DecisionEngine(
        predictor=predictor,
        bet_sizer=_BetSizer(),
        risk_manager=_Risk(),
        calibrator=_Calibrator(),
        decision_logger=logger,
    )
    return engine, logger


def test_untrained_fallback_predictor_is_fail_closed():
    engine, logger = _engine(_Predictor())

    decision = engine.evaluate_candidate("R1", {"selection": "1", "odds": 5.0, "features": {}})

    assert decision is None
    assert logger.records[-1]["skip_reason"] == "MODEL_FALLBACK_NO_BET"


def test_extreme_longshot_is_blocked_even_when_model_is_trained():
    engine, logger = _engine(_TrainedPredictor())

    decision = engine.evaluate_candidate("R1", {"selection": "1", "odds": 120.0, "features": {}})

    assert decision is None
    assert logger.records[-1]["skip_reason"] == "LONGSHOT_ODDS_LIMIT"
