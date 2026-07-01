from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Dict, Optional

from .audit_hash_log import ImmutableAuditLog
from .betting.risk_clamp import RiskClamp, RiskClampInput
from .circuit_breaker import CircuitBreaker

logger = logging.getLogger("CriticalPath")


class LowLatencyExecutionEngine:
    def __init__(
        self,
        predictor,
        risk_manager,
        ipat_client,
        audit_log: Optional[ImmutableAuditLog] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        staleness_threshold: float = 2.0,
        max_clock_skew_ms: int = 1_000,
        risk_clamp: Optional[RiskClamp] = None,
    ):
        self.predictor = predictor
        self.risk_manager = risk_manager
        self.ipat_client = ipat_client
        self.audit_log = audit_log
        self.circuit_breaker = circuit_breaker
        self.is_locked = False
        self.staleness_threshold = float(staleness_threshold)
        self.max_clock_skew_ms = int(max_clock_skew_ms)
        self.risk_clamp = risk_clamp or RiskClamp()

    def _no_bet(self, race_id: str, reason: str, breaker_reason: str | None = None) -> Dict[str, Any]:
        if breaker_reason and self.circuit_breaker is not None:
            self.circuit_breaker.force_open(breaker_reason)
        return {
            "race_id": race_id,
            "decision": "NO_BET",
            "should_bet": False,
            "reason": reason,
            "breaker_reason": breaker_reason,
        }

    def _predict_raw_safe(self, features: Any, odds: Any, submitted_at: float = None):
        predict_raw = self.predictor.predict_raw
        try:
            parameter_count = len(inspect.signature(predict_raw).parameters)
        except Exception:
            parameter_count = 2
        if parameter_count >= 3:
            return predict_raw(features, odds, submitted_at)
        if parameter_count >= 2:
            return predict_raw(features, odds)
        return predict_raw(features)

    def _is_race_cancelled(self, odds_snapshot: Dict[str, Any]) -> bool:
        status = str(odds_snapshot.get("status", "")).strip().upper()
        return bool(
            odds_snapshot.get("race_cancelled")
            or odds_snapshot.get("cancelled")
            or status in {"CANCELLED", "CANCELED", "SCRATCHED", "VOID"}
        )

    def _has_clock_skew(self, odds_snapshot: Dict[str, Any]) -> bool:
        if odds_snapshot.get("clock_skew"):
            return True
        skew_ms = odds_snapshot.get("clock_skew_ms")
        if skew_ms is None:
            return False
        try:
            return abs(float(skew_ms)) > self.max_clock_skew_ms
        except (TypeError, ValueError):
            return True

    def _extract_provider_ts(self, odds_snapshot: Dict[str, Any]) -> float | None:
        for key in ("provider_timestamp", "scraped_at", "timestamp", "fetched_at"):
            if key not in odds_snapshot:
                continue
            try:
                return float(odds_snapshot.get(key))
            except (TypeError, ValueError):
                return None
        return None

    def _feature_is_stale(self, feature_snapshot: Any) -> bool:
        if feature_snapshot is None:
            return True
        checker = getattr(feature_snapshot, "is_stale", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return True
        if isinstance(feature_snapshot, dict):
            return bool(feature_snapshot.get("stale") or feature_snapshot.get("expired"))
        return False

    def _calibration_is_expired(self, odds_snapshot: Dict[str, Any]) -> bool:
        calibration = odds_snapshot.get("calibration_state")
        if calibration is None:
            calibration = getattr(self.predictor, "calibration_state", None)
        if calibration is None:
            calibration = getattr(self.risk_manager, "calibration_state", None)
        if calibration is None:
            return bool(odds_snapshot.get("calibration_expired"))
        checker = getattr(calibration, "is_expired", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return True
        if isinstance(calibration, dict):
            return bool(calibration.get("expired") or calibration.get("stale"))
        return False

    def _bankroll_is_uncertain(self, odds_snapshot: Dict[str, Any]) -> bool:
        bankroll = odds_snapshot.get("bankroll_state")
        if bankroll is None:
            bankroll = getattr(self.risk_manager, "bankroll_state", None)
        if bankroll is None:
            return bool(odds_snapshot.get("bankroll_uncertain"))
        checker = getattr(bankroll, "is_uncertain", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return True
        if isinstance(bankroll, dict):
            return bool(bankroll.get("uncertain") or bankroll.get("stale"))
        return False

    async def execute_critical_path(self, race_id: str, timeout_sec: float = 2.0):
        start_time = time.perf_counter()
        if self.circuit_breaker is not None and self.circuit_breaker.is_open():
            logger.warning("[CIRCUIT OPEN] Skipping execution for Race %s.", race_id)
            return self._no_bet(race_id, "circuit_open")

        try:
            odds_task = self.ipat_client.fetch_live_odds_async(race_id)
            odds_snapshot = await asyncio.wait_for(odds_task, timeout=timeout_sec)
            if not odds_snapshot:
                return self._no_bet(race_id, "stale_odds", "STALE_ODDS")

            if self._is_race_cancelled(odds_snapshot):
                return self._no_bet(race_id, "race_cancelled", "RACE_CANCELLED")

            if self._has_clock_skew(odds_snapshot):
                return self._no_bet(race_id, "clock_skew", "CLOCK_SKEW")

            provider_ts = self._extract_provider_ts(odds_snapshot)
            if provider_ts is None or time.time() - provider_ts > self.staleness_threshold:
                return self._no_bet(race_id, "stale_odds", "STALE_ODDS")

            features = odds_snapshot.get("precomputed_feature_vector")
            if self._feature_is_stale(features):
                return self._no_bet(race_id, "stale_features", "STALE_FEATURES")

            if self._calibration_is_expired(odds_snapshot):
                return self._no_bet(race_id, "calibration_expired", "CALIBRATION_EXPIRED")

            if self._bankroll_is_uncertain(odds_snapshot):
                return self._no_bet(race_id, "bankroll_uncertain", "BANKROLL_STATE_UNCERTAIN")

            predicted_probs = await self._predict(odds_snapshot, features, race_id, timeout_sec)
            bet_decision = await self._size_bet(predicted_probs, odds_snapshot, timeout_sec)

            if not bet_decision.get("allowed"):
                logger.info(
                    "[NO BET] Race: %s | Execution Time: %.2fms",
                    race_id,
                    (time.perf_counter() - start_time) * 1000,
                )
                return self._no_bet(race_id, str(bet_decision.get("reason", "risk_rejected")))

            await asyncio.wait_for(
                self.ipat_client.place_bet_async(race_id, bet_decision.get("allocations")),
                timeout=timeout_sec,
            )

            if self.audit_log is not None and hasattr(self.audit_log, "enqueue_nowait"):
                self.audit_log.enqueue_nowait(
                    {"race_id": race_id, "odds_snapshot": odds_snapshot, "decision": bet_decision}
                )

            logger.info(
                "[BET EXECUTED] Race: %s | Latency: %.2fms",
                race_id,
                (time.perf_counter() - start_time) * 1000,
            )
            return {
                "race_id": race_id,
                "decision": "BET",
                "should_bet": True,
                "reason": "submitted",
                "allocations": bet_decision.get("allocations", []),
            }

        except asyncio.TimeoutError:
            logger.critical("[CRITICAL TIMEOUT] Critical path exceeded timeout on Race %s.", race_id)
            await self.trigger_emergency_safeguard(race_id, reason="RETRY_BUDGET_EXCEEDED")
            return self._no_bet(race_id, "prediction_timeout", "RETRY_BUDGET_EXCEEDED")
        except Exception as exc:
            logger.error("[EXECUTION FAILURE] Critical path failed: %s", exc)
            await self.trigger_emergency_safeguard(race_id)
            return self._no_bet(race_id, "execution_failure")

    async def _predict(self, odds_snapshot: Dict[str, Any], features: Any, race_id: str, timeout_sec: float):
        loop = asyncio.get_running_loop()
        if hasattr(self.predictor, "predict_raw"):
            odds = odds_snapshot.get("odds")
            odds_values = odds if isinstance(odds, (list, tuple)) else None
            feature_items = features if isinstance(features, (list, tuple)) else [features]
            probs = []
            for idx, item in enumerate(feature_items):
                feature_payload = item if isinstance(item, dict) else {f"feature_{idx}": item}
                odds_for_item = (
                    odds_values[idx]
                    if odds_values is not None and idx < len(odds_values)
                    else odds_values[-1] if odds_values else odds
                )
                executor = getattr(self.predictor, "predict_executor", None)
                submitted = time.perf_counter()
                prob = await asyncio.wait_for(
                    loop.run_in_executor(
                        executor,
                        self._predict_raw_safe,
                        feature_payload,
                        odds_for_item,
                        submitted,
                    ),
                    timeout=timeout_sec,
                )
                probs.append(prob)
            return probs

        if not hasattr(self.predictor, "predict"):
            raise RuntimeError("predictor has no compatible predict method")

        feature_items = features if isinstance(features, (list, tuple)) else [features]
        probs = []
        for sel_idx, feat in enumerate(feature_items):
            prob = await asyncio.wait_for(
                asyncio.to_thread(
                    self.predictor.predict,
                    race_id,
                    sel_idx,
                    feat,
                    odds_snapshot.get("odds"),
                ),
                timeout=timeout_sec,
            )
            probs.append(prob)
        return probs

    async def _size_bet(self, predicted_probs: Any, odds_snapshot: Dict[str, Any], timeout_sec: float):
        proposal: Dict[str, Any]
        if not hasattr(self.risk_manager, "calculate_sizing"):
            proposal = {"should_bet": False, "allocations": [], "reason": "missing_risk_sizer"}
        else:
            try:
                proposal = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.risk_manager.calculate_sizing,
                        predicted_probs,
                        odds_snapshot.get("odds"),
                    ),
                    timeout=timeout_sec,
                )
            except Exception:
                logger.exception("Risk sizing failed or timed out; forcing no-bet")
                proposal = {"should_bet": False, "allocations": [], "reason": "risk_sizing_failed"}

        allocations = proposal.get("allocations") if isinstance(proposal, dict) else []
        if not isinstance(allocations, list):
            allocations = []
        proposed_stake = 0.0
        for allocation in allocations:
            if not isinstance(allocation, dict):
                continue
            try:
                proposed_stake += float(allocation.get("amount", 0.0))
            except (TypeError, ValueError):
                continue

        provider_ts = self._extract_provider_ts(odds_snapshot)
        odds_freshness_ms = None
        if provider_ts is not None:
            odds_freshness_ms = max(0.0, (time.time() - provider_ts) * 1000.0)

        features = odds_snapshot.get("precomputed_feature_vector")
        calibration_state = odds_snapshot.get("calibration_state") or {}
        bankroll_state = odds_snapshot.get("bankroll_state") or {}
        risk_result = self.risk_clamp.evaluate(
            RiskClampInput(
                odds_snapshot={
                    "present": bool(odds_snapshot),
                    "missing": not bool(odds_snapshot),
                    "stale": provider_ts is None,
                },
                feature_snapshot={
                    "present": features is not None,
                    "missing": features is None,
                    "stale": self._feature_is_stale(features),
                },
                prediction_snapshot={"predicted_probs": predicted_probs},
                calibration_state=calibration_state if isinstance(calibration_state, dict) else {},
                uncertainty_state={},
                bankroll_snapshot=bankroll_state if isinstance(bankroll_state, dict) else {},
                regime_state={},
                race_state={"race_cancelled": self._is_race_cancelled(odds_snapshot)},
                clock_state={
                    "clock_skew_ms": odds_snapshot.get("clock_skew_ms", 0),
                    "skew": bool(odds_snapshot.get("clock_skew")),
                },
                exposure_snapshot={},
                policy_snapshot={
                    "policy_hash": "low_latency_policy_v1",
                    "max_odds_age_ms": self.staleness_threshold * 1000.0,
                    "max_clock_skew_ms": float(self.max_clock_skew_ms),
                },
                model_state={"model_hash": getattr(self.predictor, "model_hash", "unknown")},
                sizing_proposal={
                    "allowed": bool(proposal.get("should_bet")) and bool(allocations),
                    "max_stake": proposed_stake,
                    "risk_multiplier": proposal.get("risk_multiplier", 1.0),
                    "reason": proposal.get("reason", "OK"),
                },
                odds_freshness_ms=odds_freshness_ms,
                feature_age_ms=0.0 if features is not None else None,
            )
        )

        if not risk_result.allowed or not allocations:
            return {
                "allowed": False,
                "should_bet": False,
                "allocations": [],
                "reason": risk_result.reason,
                "risk_limits_hash": risk_result.risk_limits_hash,
            }

        return {
            "allowed": True,
            "should_bet": True,
            "allocations": allocations,
            "reason": "risk_clamp_allowed",
            "risk_limits_hash": risk_result.risk_limits_hash,
            "max_stake": risk_result.max_stake,
            "risk_multiplier": risk_result.risk_multiplier,
        }

    async def persist_audit_log(self, race_id: str, odds: Dict, decision: Dict):
        record = {"race_id": race_id, "odds_snapshot": odds, "decision": decision}
        try:
            await self.audit_log.append_async(record)
        except Exception:
            logger.exception("Failed to persist audit log")

    async def trigger_emergency_safeguard(self, race_id: str, reason: str = "FAILURE_THRESHOLD"):
        self.is_locked = True
        logger.warning("[CIRCUIT BREAKER] Safely isolated system for race %s.", race_id)
        if self.circuit_breaker is not None:
            self.circuit_breaker.force_open(reason)
