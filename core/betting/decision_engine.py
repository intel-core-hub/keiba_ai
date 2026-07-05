import os
from dataclasses import dataclass

from core.execution.calibration_refit import CalibrationRefitJob
from core.prediction.calibration import ProbabilityCalibrator
from core.prediction.edge_calculator import EdgeCalculator
from core.prediction.edge_quality_filter import EdgeQualityFilter
from core.betting.bet_types import (
    apply_fraction_multiplier,
    default_registry,
    normalize_legacy_win_record,
)
from core.betting.risk_clamp import RiskClamp, RiskClampInput
from core.betting.uncertainty_bankroll_manager import UncertaintyBankrollManager
from core.betting.uncertainty_filter import UncertaintyFilter, UncertaintyFilterConfig
from core.survival.degradation_mode import (
    DegradationSignals,
    apply_degradation_to_bet,
    encode_reasons,
    evaluate_degradation,
    limit_candidates_by_degradation,
)


def estimate_uncertainty(probability, profile=None):
    """Runtime-safe uncertainty estimate without importing offline learning modules."""
    probability = float(max(0.0, min(1.0, probability)))
    profile = profile or {}
    center = float(profile.get("center", 0.5)) if isinstance(profile, dict) else 0.5
    width = float(profile.get("width", 0.5)) if isinstance(profile, dict) else 0.5
    distance = min(width, abs(probability - center))
    uncertainty_score = 1.0 - (distance / max(width, 1e-9))
    return {"uncertainty_score": float(max(0.0, min(1.0, uncertainty_score)))}


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
    risk_limits_hash: str = ""
    risk_clamp_reason: str = ""
    risk_clamp_allowed: bool = False
    policy_hash: str = ""
    model_hash: str = ""
    odds_snapshot_hash: str = ""
    feature_snapshot_hash: str = ""
    bet_type: str = "win"
    legs: tuple[str, ...] = ()
    ordered: bool = False
    shadow_only: bool = False
    production_candidate: bool = True
    max_combinations_per_race: int = 1
    max_race_exposure_share: float = 0.50
    source: str = ""
    degradation_mode: str = "NORMAL"
    degradation_reasons: tuple[str, ...] = ()
    degradation_stake_multiplier: float = 1.0
    degradation_allowed_bet_types: tuple[str, ...] = ("win", "place", "wide")
    degradation_coverage_lower_bound: float = 0.05
    degradation_coverage_upper_bound: float = 0.30
    degradation_max_race_exposure_multiplier: float = 1.0
    degradation_force_no_bet: bool = False
    degradation_requires_operator_ack: bool = False
    degradation_fail_closed: bool = False


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
        risk_clamp=None,
        degradation_policy=None,
        degradation_signals_provider=None,
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
        self.risk_clamp = risk_clamp or RiskClamp()
        self.degradation_policy = degradation_policy
        self.degradation_signals_provider = degradation_signals_provider
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
        self.longshot_max_odds = float(os.getenv("LONGSHOT_MAX_ODDS", "50"))
        self.longshot_prob_gap_limit = float(os.getenv("LONGSHOT_PROB_GAP_LIMIT", "0.08"))
        self.longshot_prob_ratio_limit = float(os.getenv("LONGSHOT_PROB_RATIO_LIMIT", "6"))
        self.allow_fallback_betting = os.getenv("ALLOW_FALLBACK_BETTING", "0").lower() in {"1", "true", "yes"}

    def _sanity_guard_reason(self, *, odds, calibrated_probability, market_probability):
        if not self.allow_fallback_betting and not bool(getattr(self.predictor, "trained", False)):
            return "MODEL_FALLBACK_NO_BET"

        odds = float(odds)
        calibrated_probability = float(calibrated_probability)
        market_probability = float(market_probability)

        if odds > self.longshot_max_odds:
            return "LONGSHOT_ODDS_LIMIT"

        probability_gap = calibrated_probability - market_probability
        if odds >= 30.0 and probability_gap > self.longshot_prob_gap_limit:
            return "LONGSHOT_PROB_GAP"

        if market_probability > 0:
            probability_ratio = calibrated_probability / market_probability
            if odds >= 20.0 and probability_ratio > self.longshot_prob_ratio_limit:
                return "LONGSHOT_MARKET_PROB_RATIO"

        return None

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
            decision="NO_BET" if skipped else "BET",
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
            bet_type=getattr(decision, "bet_type", "win"),
            legs=list(getattr(decision, "legs", ()) or (decision.selection,)),
            ordered=getattr(decision, "ordered", False),
            shadow_only=getattr(decision, "shadow_only", False),
            production_candidate=getattr(decision, "production_candidate", True),
            max_combinations_per_race=getattr(decision, "max_combinations_per_race", 1),
            max_race_exposure_share=getattr(decision, "max_race_exposure_share", 0.50),
            degradation_mode=getattr(decision, "degradation_mode", "NORMAL"),
            degradation_reasons=encode_reasons(getattr(decision, "degradation_reasons", ())),
            degradation_stake_multiplier=getattr(decision, "degradation_stake_multiplier", 1.0),
            degradation_allowed_bet_types=list(getattr(decision, "degradation_allowed_bet_types", ("win", "place", "wide"))),
            degradation_force_no_bet=getattr(decision, "degradation_force_no_bet", False),
            source=getattr(decision, "source", ""),
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

    def _risk_provider_snapshot(self):
        snapshot = {
            "can_bet": False,
            "risk_multiplier": 0.0,
            "max_bet_size": 0.0,
            "status": {},
        }
        if self.risk_manager is None:
            return snapshot

        try:
            if hasattr(self.risk_manager, "status"):
                snapshot["status"] = self.risk_manager.status() or {}
        except Exception:
            snapshot["status"] = {}

        try:
            snapshot["can_bet"] = bool(self.risk_manager.can_bet())
        except Exception:
            snapshot["can_bet"] = False

        try:
            snapshot["risk_multiplier"] = float(self.risk_manager.risk_multiplier())
        except Exception:
            snapshot["risk_multiplier"] = 0.0

        try:
            snapshot["max_bet_size"] = float(self.risk_manager.max_bet_size())
        except Exception:
            snapshot["max_bet_size"] = 0.0

        return snapshot

    def _degradation_signals_for_candidate(self, candidate, risk_status):
        if isinstance(candidate, dict) and isinstance(candidate.get("degradation_signals"), dict):
            return DegradationSignals.from_mapping(candidate.get("degradation_signals"))
        if self.degradation_signals_provider is not None:
            try:
                return DegradationSignals.from_mapping(self.degradation_signals_provider(candidate, risk_status))
            except TypeError:
                return DegradationSignals.from_mapping(self.degradation_signals_provider())
            except Exception:
                return DegradationSignals.from_mapping({"data_quality_score": 0.0, "timeout_rate": 1.0})
        drawdown = risk_status.get("drawdown_pct", risk_status.get("drawdown", 0.0)) if isinstance(risk_status, dict) else 0.0
        loss_streak = risk_status.get("loss_streak", risk_status.get("lose_streak", 0)) if isinstance(risk_status, dict) else 0
        return DegradationSignals.from_mapping(
            {
                "data_quality_score": 1.0,
                "missing_odds_rate": 0.0,
                "stale_odds_rate": 0.0,
                "missing_features_rate": 0.0,
                "loss_streak": loss_streak,
                "drawdown_pct": drawdown,
                "latency_p99_ms": 0.0,
                "latency_regression_rate": 0.0,
                "drift_gap50": float(self.calibration_state.get("drift_gap50", 0.0) or 0.0),
                "feature_psi_max": float(self.calibration_state.get("feature_psi_max", 0.0) or 0.0),
                "odds_distribution_psi": float(self.calibration_state.get("odds_distribution_psi", 0.0) or 0.0),
                "timeout_rate": 0.0,
            }
        )

    # -------------------------------------------------
    # 単一候補評価
    # -------------------------------------------------

    def evaluate_candidate(self, race_id, candidate):

        try:
            registry = default_registry()
            explicit_bet_type = bool(candidate.get("bet_type"))
            bet_data = normalize_legacy_win_record({**candidate, "race_id": race_id}, registry=registry)
            bet_config = registry.get(bet_data["bet_type"])
        except ValueError:
            return None

        if not bet_config.enabled:
            return None

        legs = tuple(bet_data["legs"])
        selection = str(candidate.get("selection") or "-".join(legs))
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

        sanity_reason = self._sanity_guard_reason(
            odds=odds,
            calibrated_probability=calibrated_prob,
            market_probability=market_probability,
        )
        if sanity_reason:
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
                skip_reason=sanity_reason,
            )
            self._log_decision(d, skipped=True, skip_reason=d.skip_reason, features=features)
            return None

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

        degradation_decision = evaluate_degradation(
            self._degradation_signals_for_candidate(candidate, risk_status),
            policy=self.degradation_policy,
        )
        allowed, _, degradation_block_reason = apply_degradation_to_bet(
            bet_type=bet_config.bet_type,
            stake=1.0,
            decision=degradation_decision,
        )
        if not allowed:
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
                skip_reason=degradation_block_reason or "degradation_bet_type_excluded",
                bet_type=bet_config.bet_type,
                legs=legs,
                ordered=bet_config.ordered,
                shadow_only=bet_config.shadow_only,
                production_candidate=bet_config.production_candidate,
                max_combinations_per_race=bet_config.max_combinations_per_race,
                max_race_exposure_share=bet_config.max_race_exposure_share,
                source=str(candidate.get("source") or ""),
                degradation_mode=degradation_decision.mode,
                degradation_reasons=tuple(degradation_decision.reasons),
                degradation_stake_multiplier=degradation_decision.stake_multiplier,
                degradation_allowed_bet_types=tuple(degradation_decision.allowed_bet_types),
                degradation_coverage_lower_bound=degradation_decision.coverage_lower_bound,
                degradation_coverage_upper_bound=degradation_decision.coverage_upper_bound,
                degradation_max_race_exposure_multiplier=degradation_decision.max_race_exposure_multiplier,
                degradation_force_no_bet=degradation_decision.force_no_bet,
                degradation_requires_operator_ack=degradation_decision.requires_operator_ack,
                degradation_fail_closed=degradation_decision.fail_closed,
            )
            self._log_decision(d, skipped=True, skip_reason=d.skip_reason, features=features)
            return None

        proposal_no_bet_reason = None
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
                proposal_no_bet_reason = str(reason)

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

        risk_provider = self._risk_provider_snapshot()
        risk_can_bet = bool(risk_provider["can_bet"])
        risk_multiplier = float(risk_provider["risk_multiplier"])

        # keep the legacy uncertainty filter as a rolling sample buffer only
        try:
            self.uncertainty_filter.add_sample(uncertainty_score)
        except Exception:
            pass

        try:
            proposed_size = self.bet_sizer.calculate_bet(
                bankroll=self.risk_manager.bankroll,
                prob=float(calibrated_prob),
                odds=odds,
                risk_multiplier=risk_multiplier,
            )
        except Exception:
            proposed_size = 0
            proposal_no_bet_reason = proposal_no_bet_reason or "risk_limits_invalid"

        max_allowed = float(risk_provider["max_bet_size"])
        bankroll = float(getattr(self.risk_manager, "bankroll", 0.0) or 0.0)
        if bankroll > 0:
            max_allowed = min(max_allowed, bankroll * float(bet_config.max_race_exposure_share))
        max_allowed *= float(degradation_decision.max_race_exposure_multiplier)

        proposed_size = int(apply_fraction_multiplier(proposed_size, bet_config.bet_type, registry=registry))
        proposed_size = int(proposed_size * float(degradation_decision.stake_multiplier))
        proposed_size = min(int(proposed_size), int(max_allowed))
        sizing_proposal = {
            "allowed": bool(risk_can_bet and proposed_size > 0 and risk_multiplier > 0.0),
            "max_stake": float(proposed_size),
            "risk_multiplier": float(risk_multiplier),
            "reason": proposal_no_bet_reason or ("OK" if risk_can_bet else "risk_limits_invalid"),
        }

        risk_result = self.risk_clamp.evaluate(
            RiskClampInput(
                odds_snapshot={"present": True, "odds": float(odds)},
                feature_snapshot={"present": features is not None, "missing": features is None},
                prediction_snapshot={
                    "probability": float(raw_prob),
                    "calibrated_probability": float(calibrated_prob),
                    "expected_value": float(expected_value),
                    "edge": float(edge),
                },
                calibration_state=dict(self.calibration_state or {}),
                uncertainty_state={
                    "uncertainty_score": float(uncertainty_score),
                    "edge_quality": float(quality),
                    "drift_score": float(self.calibration_state.get("drift_score") or 0.0),
                },
                bankroll_snapshot=dict(risk_status or {}),
                regime_state={"regime": regime},
                race_state={"race_id": race_id},
                clock_state={"clock_skew_ms": 0.0},
                exposure_snapshot={"max_allowed": float(max_allowed)},
                policy_snapshot={"policy_hash": "decision_engine_policy_v1"},
                model_state={"model_hash": getattr(self.predictor, "model_hash", "unknown")},
                sizing_proposal=sizing_proposal,
                odds_freshness_ms=0.0,
                feature_age_ms=0.0,
            )
        )

        if not risk_result.allowed:
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
                skip_reason=risk_result.reason,
            )
            self._log_decision(d, skipped=True, skip_reason=d.skip_reason, features=features)
            return None

        # Shadow-only bet types keep a virtual stake for evaluation, but never consume live race risk.
        if not bet_config.shadow_only:
            self.risk_manager.register_bet(risk_result.max_stake)

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
            bet_size=int(risk_result.max_stake),
            risk_limits_hash=risk_result.risk_limits_hash,
            risk_clamp_reason=risk_result.reason,
            risk_clamp_allowed=True,
            policy_hash="decision_engine_policy_v1",
            model_hash=str(getattr(self.predictor, "model_hash", "unknown")),
            odds_snapshot_hash=str(candidate.get("odds_snapshot_hash") or "decision_engine_odds_snapshot"),
            feature_snapshot_hash=str(candidate.get("feature_snapshot_hash") or "decision_engine_feature_snapshot"),
            bet_type=bet_config.bet_type,
            legs=legs,
            ordered=bet_config.ordered,
            shadow_only=bet_config.shadow_only,
            production_candidate=bet_config.production_candidate,
            max_combinations_per_race=(
                bet_config.max_combinations_per_race if explicit_bet_type else self.max_per_race
            ),
            max_race_exposure_share=bet_config.max_race_exposure_share,
            source=str(candidate.get("source") or ""),
            degradation_mode=degradation_decision.mode,
            degradation_reasons=tuple(degradation_decision.reasons),
            degradation_stake_multiplier=degradation_decision.stake_multiplier,
            degradation_allowed_bet_types=tuple(degradation_decision.allowed_bet_types),
            degradation_coverage_lower_bound=degradation_decision.coverage_lower_bound,
            degradation_coverage_upper_bound=degradation_decision.coverage_upper_bound,
            degradation_max_race_exposure_multiplier=degradation_decision.max_race_exposure_multiplier,
            degradation_force_no_bet=degradation_decision.force_no_bet,
            degradation_requires_operator_ack=degradation_decision.requires_operator_ack,
            degradation_fail_closed=degradation_decision.fail_closed,
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
        by_bet_type = {}

        for d in decisions:

            horses = set(d.selection.split("-"))
            bet_type = getattr(d, "bet_type", "win")
            bet_type_count = by_bet_type.get(bet_type, 0)
            max_combinations = int(getattr(d, "max_combinations_per_race", self.max_per_race) or self.max_per_race)
            if bet_type_count >= max_combinations:
                continue

            # 同一馬重複排除
            if horses & used_horses:
                continue

            final.append(d)
            used_horses |= horses
            by_bet_type[bet_type] = bet_type_count + 1

            if len(final) >= self.max_per_race:
                break

        degraded = [d for d in final if getattr(d, "degradation_mode", "NORMAL") != "NORMAL"]
        if degraded:
            strictest = min(degraded, key=lambda d: float(getattr(d, "degradation_coverage_upper_bound", 1.0)))
            return limit_candidates_by_degradation(
                final,
                evaluate_degradation(
                    {
                        "data_quality_score": 0.94 if getattr(strictest, "degradation_mode", "") == "WARNING" else 0.89,
                        "missing_odds_rate": 0.0,
                        "stale_odds_rate": 0.0,
                        "missing_features_rate": 0.0,
                        "loss_streak": 0,
                        "drawdown_pct": 0.0,
                        "latency_p99_ms": 0.0,
                        "latency_regression_rate": 0.0,
                        "drift_gap50": 0.0,
                        "feature_psi_max": 0.0,
                        "odds_distribution_psi": 0.0,
                        "timeout_rate": 0.0,
                    },
                    policy=self.degradation_policy,
                ),
            )

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
