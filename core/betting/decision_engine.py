from dataclasses import dataclass

from core.execution.calibration_refit import CalibrationRefitJob
from core.prediction.calibration import ProbabilityCalibrator
from core.prediction.edge_calculator import EdgeCalculator
from core.prediction.edge_quality_filter import EdgeQualityFilter
from learning.uncertainty import estimate_uncertainty
from core.betting.uncertainty_bankroll_manager import UncertaintyBankrollManager
from core.betting.uncertainty_filter import UncertaintyFilter, UncertaintyFilterConfig


# =====================================================
# Decision Data
# =====================================================

@dataclass
class Decision:

    race_id: str
    selection: str
    probability: float
    calibrated_probability: float
    market_probability: float
    odds: float
    edge: float
    expected_value: float
    uncertainty_score: float
    edge_quality: float
    bet_size: int
    skip_reason: str = ""


# =====================================================
# Decision Engine
# =====================================================

class DecisionEngine:

    def __init__(
        self,
        predictor,
        bet_sizer,
        risk_manager,
        no_bet_filter=None,
        decision_logger=None,
        telemetry=None,
        edge_calculator=None,
        edge_quality_filter=None,
        calibrator=None,
        uncertainty_profile=None,
        max_uncertainty=0.65,
    ):

        self.predictor = predictor
        self.bet_sizer = bet_sizer
        if risk_manager is not None and not hasattr(risk_manager, "update_uncertainty_state"):
            self.risk_manager = UncertaintyBankrollManager(risk_manager)
        else:
            self.risk_manager = risk_manager

        self.no_bet_filter = no_bet_filter
        self.decision_logger = decision_logger
        self.telemetry = telemetry

        self.edge_calculator = edge_calculator or EdgeCalculator()
        self.edge_quality_filter = edge_quality_filter or EdgeQualityFilter()
        if calibrator is None:
            self.calibrator = CalibrationRefitJob(
                auto_refit_enabled=False,
            ).load_calibrator(ProbabilityCalibrator())
        else:
            self.calibrator = calibrator

        self.uncertainty_profile = uncertainty_profile
        self.max_uncertainty = max_uncertainty
        # uncertainty filter: can be overridden via set_uncertainty_profile
        self.uncertainty_filter = UncertaintyFilter(UncertaintyFilterConfig(threshold=0.50, high_threshold=self.max_uncertainty))

        self.calibration_state = {
            "brier": None,
            "ece": None,
            "reliability": None,
            "drift_score": None,
            "mean_brier": None,
            "mean_ece": None,
            "mean_reliability": None,
        }

        self.max_per_race = 3

    def set_calibration_state(self, calibration_state=None):

        if calibration_state is None:
            return

        self.calibration_state.update(calibration_state)

    def set_uncertainty_profile(self, profile=None, max_uncertainty=None):

        if profile is not None:
            self.uncertainty_profile = profile

        if max_uncertainty is not None:
            self.max_uncertainty = float(max_uncertainty)

    def _calibration_multiplier(self):

        state = self.calibration_state or {}

        brier = state.get("mean_brier", state.get("brier"))
        ece = state.get("mean_ece", state.get("ece"))
        reliability = state.get("mean_reliability", state.get("reliability"))

        penalty = 1.0

        if brier is not None:
            if brier > 0.24:
                penalty *= 0.55
            elif brier > 0.20:
                penalty *= 0.75

        if ece is not None:
            if ece > 0.07:
                penalty *= 0.60
            elif ece > 0.04:
                penalty *= 0.80

        if reliability is not None:
            if reliability < 0.90:
                penalty *= 0.70
            elif reliability < 0.94:
                penalty *= 0.85

        return float(max(0.0, min(1.0, penalty)))

    def _log_decision(self, decision, skipped=False, skip_reason=None, features=None):

        if self.decision_logger is None:
            return

        risk_status = {}
        if self.risk_manager is not None and hasattr(self.risk_manager, "status"):
            try:
                risk_status = self.risk_manager.status() or {}
            except Exception:
                risk_status = {}

        self.decision_logger.log_decision(
            race_id=decision.race_id,
            selection=decision.selection,
            probability=decision.probability,
            odds=decision.odds,
            edge=decision.edge,
            decision="BUY" if not skipped else "SKIP",
            skipped=skipped,
            skip_reason=skip_reason,
            final_size=decision.bet_size,
            bankroll=self.risk_manager.bankroll,
            brier_score=self.calibration_state.get("mean_brier", self.calibration_state.get("brier")),
            ece=self.calibration_state.get("mean_ece", self.calibration_state.get("ece")),
            reliability=self.calibration_state.get("mean_reliability", self.calibration_state.get("reliability")),
            drift_score=self.calibration_state.get("drift_score"),
            expected_value=decision.expected_value,
            market_probability=decision.market_probability,
            calibrated_probability=decision.calibrated_probability,
            uncertainty_score=decision.uncertainty_score,
            edge_quality=decision.edge_quality,
            risk_status=risk_status,
            uncertainty_multiplier=risk_status.get("uncertainty_multiplier"),
            global_exposure_multiplier=risk_status.get("global_exposure_multiplier"),
            defensive_mode=risk_status.get("defensive_mode"),
            rolling_uncertainty=risk_status.get("rolling_uncertainty"),
            uncertainty_deteriorating=risk_status.get("deteriorating"),
            no_bet_reason=skip_reason,
            features=features,
        )

    def _record_telemetry(self, decision):

        if self.telemetry is None:
            return

        self.telemetry.record_metric("pred_prob", float(decision.probability))
        self.telemetry.record_metric("calibrated_prob", float(decision.calibrated_probability))
        self.telemetry.record_metric("uncertainty", float(decision.uncertainty_score))
        self.telemetry.record_metric("edge", float(decision.edge))
        self.telemetry.record_metric("expected_value", float(decision.expected_value))
        self.telemetry.record_metric("bet_size", float(decision.bet_size))

    # -------------------------------------------------
    # 単一候補評価
    # -------------------------------------------------

    def evaluate_candidate(self, race_id, candidate):

        selection = candidate["selection"]
        odds = candidate["odds"]
        features = candidate.get("features", {})
        regime = candidate.get("regime")

        if odds is None or odds <= 1.0:
            return None

        raw_prob = self.predictor.predict(
            race_id,
            selection,
            features,
            odds=odds,
        )

        calibrated_prob = self.calibrator.calibrate(float(raw_prob))

        uncertainty = estimate_uncertainty(
            calibrated_prob,
            profile=self.uncertainty_profile,
        )
        uncertainty_score = float(uncertainty.get("uncertainty_score", 0.0))

        edge_info = self.edge_calculator.calculate_edge(
            ai_prob=calibrated_prob,
            odds=float(odds),
            regime=regime,
        )
        edge = float(edge_info["edge"])
        expected_value = float(edge_info["expected_value"])
        market_probability = float(edge_info["market_prob"])

        quality = self.edge_quality_filter.evaluate(
            ai_prob=calibrated_prob,
            market_prob=market_probability,
            edge=edge,
            odds=float(odds),
            recent_brier=float(self.calibration_state.get("mean_brier", self.calibration_state.get("brier", 0.15)) or 0.15),
            uncertainty_score=float(uncertainty_score),
            drift_score=float(self.calibration_state.get("drift_score") or 0.0),
        )

        if quality < self.edge_quality_filter.min_quality:
            d = Decision(
                race_id=race_id,
                selection=selection,
                probability=float(raw_prob),
                calibrated_probability=float(calibrated_prob),
                market_probability=float(market_probability),
                odds=float(odds),
                edge=float(edge),
                expected_value=float(expected_value),
                uncertainty_score=float(uncertainty_score),
                edge_quality=float(quality),
                bet_size=0,
                skip_reason="LOW_EDGE_QUALITY",
            )
            self._log_decision(d, skipped=True, skip_reason=d.skip_reason, features=features)
            return None

        if uncertainty_score > self.max_uncertainty:
            d = Decision(
                race_id=race_id,
                selection=selection,
                probability=float(raw_prob),
                calibrated_probability=float(calibrated_prob),
                market_probability=float(market_probability),
                odds=float(odds),
                edge=float(edge),
                expected_value=float(expected_value),
                uncertainty_score=float(uncertainty_score),
                edge_quality=float(quality),
                bet_size=0,
                skip_reason="HIGH_UNCERTAINTY",
            )
            self._log_decision(d, skipped=True, skip_reason=d.skip_reason, features=features)
            return None

        # register sample and check uncertainty filter
        try:
            self.uncertainty_filter.add_sample(uncertainty_score)
            skip_u, reason_u = self.uncertainty_filter.should_skip(uncertainty_score)
            if skip_u:
                d = Decision(
                    race_id=race_id,
                    selection=selection,
                    probability=float(raw_prob),
                    calibrated_probability=float(calibrated_prob),
                    market_probability=float(market_probability),
                    odds=float(odds),
                    edge=float(edge),
                    expected_value=float(expected_value),
                    uncertainty_score=float(uncertainty_score),
                    edge_quality=float(quality),
                    bet_size=0,
                    skip_reason=str(reason_u),
                )
                self._log_decision(d, skipped=True, skip_reason=d.skip_reason, features=features)
                return None
        except Exception:
            # conservative: continue if filter fails
            pass

        if not self.edge_calculator.is_bettable(edge, expected_value):
            d = Decision(
                race_id=race_id,
                selection=selection,
                probability=float(raw_prob),
                calibrated_probability=float(calibrated_prob),
                market_probability=float(market_probability),
                odds=float(odds),
                edge=float(edge),
                expected_value=float(expected_value),
                uncertainty_score=float(uncertainty_score),
                edge_quality=float(quality),
                bet_size=0,
                skip_reason="INSUFFICIENT_EDGE",
            )
            self._log_decision(d, skipped=True, skip_reason=d.skip_reason, features=features)
            return None

        calibration_brier = self.calibration_state.get("mean_brier", self.calibration_state.get("brier"))

        if hasattr(self.risk_manager, "update_uncertainty_state"):
            try:
                self.risk_manager.update_uncertainty_state(
                    uncertainty_score=float(uncertainty_score),
                    drift_score=float(self.calibration_state.get("drift_score") or 0.0),
                    calibration_gap=abs(float(calibrated_prob) - float(market_probability)),
                    drawdown=float(self.risk_manager.drawdown()),
                    edge=float(edge),
                    edge_quality=float(quality),
                )
            except Exception:
                pass

        risk_status = {}
        if self.risk_manager is not None and hasattr(self.risk_manager, "status"):
            try:
                risk_status = self.risk_manager.status() or {}
            except Exception:
                risk_status = {}

        if self.no_bet_filter is not None:
            skip, reason = self.no_bet_filter.should_skip(
                probability=float(calibrated_prob),
                odds=float(odds),
                edge=float(edge),
                bankroll_status=self.risk_manager.status(),
                brier_status=calibration_brier,
                uncertainty_score=uncertainty_score,
                edge_quality=quality,
                drift_score=float(self.calibration_state.get("drift_score") or 0.0),
                defensive_mode=risk_status.get("defensive_mode"),
            )
            if skip:
                d = Decision(
                    race_id=race_id,
                    selection=selection,
                    probability=float(raw_prob),
                    calibrated_probability=float(calibrated_prob),
                    market_probability=float(market_probability),
                    odds=float(odds),
                    edge=float(edge),
                    expected_value=float(expected_value),
                    uncertainty_score=float(uncertainty_score),
                    edge_quality=float(quality),
                    bet_size=0,
                    skip_reason=str(reason),
                )
                self._log_decision(d, skipped=True, skip_reason=d.skip_reason, features=features)
                return None

        if not self.risk_manager.can_bet():
            return None

        # push calibration state to risk manager if available
        if hasattr(self.risk_manager, "update_calibration_state"):
            try:
                self.risk_manager.update_calibration_state(self.calibration_state)
            except Exception:
                pass

        # allow risk manager to adjust bet_sizer parameters if supported
        if hasattr(self.risk_manager, "adjust_bet_sizer"):
            try:
                self.risk_manager.adjust_bet_sizer(self.bet_sizer)
            except Exception:
                pass

        risk_multiplier = float(self.risk_manager.risk_multiplier())

        if risk_multiplier <= 0.0:
            return None

        # keep the legacy uncertainty filter as a rolling sample buffer only
        try:
            self.uncertainty_filter.add_sample(uncertainty_score)
        except Exception:
            pass

        bet_size = self.bet_sizer.calculate_bet(
            bankroll=self.risk_manager.bankroll,
            prob=float(calibrated_prob),
            odds=odds,
            risk_multiplier=risk_multiplier,
        )

        max_allowed = self.risk_manager.max_bet_size()

        bet_size = min(bet_size, int(max_allowed))

        if bet_size <= 0:
            return None

        # ★ Risk登録（これが最重要1行）
        self.risk_manager.register_bet(bet_size)

        decision = Decision(
            race_id=race_id,
            selection=selection,
            probability=float(raw_prob),
            calibrated_probability=float(calibrated_prob),
            market_probability=float(market_probability),
            odds=float(odds),
            edge=float(edge),
            expected_value=float(expected_value),
            uncertainty_score=float(uncertainty_score),
            edge_quality=float(quality),
            bet_size=bet_size,
        )

        self._log_decision(decision, skipped=False, skip_reason=None, features=features)
        self._record_telemetry(decision)

        return decision

    # -------------------------------------------------
    # レース意思決定
    # -------------------------------------------------

    def decide_race(self, race_id, candidates):

        # ★ レース単位Exposure初期化
        self.risk_manager.reset_race_risk()

        decisions = []

        for c in candidates:

            decision = self.evaluate_candidate(
                race_id,
                c,
            )

            if decision:
                decisions.append(decision)

        if not decisions:
            return []

        # Edge順
        decisions.sort(key=lambda d: d.edge, reverse=True)

        # -------------------------------------------------
        # 相関分散制御（プロ仕様）
        # -------------------------------------------------

        final = []
        used_horses = set()

        for d in decisions:

            horses = set(d.selection.split("-"))

            # 同一馬重複排除
            if horses & used_horses:
                continue

            final.append(d)
            used_horses |= horses

            if len(final) >= self.max_per_race:
                break

        return final

    # -------------------------------------------------
    # 結果更新
    # -------------------------------------------------

    def update_result(self, decision, hit: bool):

        if hit:
            profit = decision.bet_size * (decision.odds - 1)
        else:
            profit = -decision.bet_size

        self.risk_manager.update_after_race(profit)

        if self.decision_logger is not None:
            self.decision_logger.log_outcome(
                race_id=decision.race_id,
                selection=decision.selection,
                hit=bool(hit),
                profit=float(profit),
                bankroll_after=float(self.risk_manager.bankroll),
                drawdown=float(self.risk_manager.drawdown()),
                survival_score=float(self.risk_manager.risk_multiplier()),
            )

        if self.telemetry is not None:
            self.telemetry.record_metric("profit", float(profit))
            self.telemetry.record_metric("bankroll", float(self.risk_manager.bankroll))

        return profit
