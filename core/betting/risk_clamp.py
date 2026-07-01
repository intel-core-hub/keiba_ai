from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping


VALID_NO_BET_REASONS = {
    "stale_odds",
    "missing_odds",
    "stale_features",
    "missing_features",
    "calibration_expired",
    "calibration_invalid",
    "bankroll_uncertain",
    "bankroll_stale",
    "race_cancelled",
    "clock_skew",
    "risk_limits_invalid",
    "policy_hash_mismatch",
    "model_hash_mismatch",
    "session_expired",
    "ip_blocked",
    "retry_budget_exceeded",
    "odds_spike",
    "audit_enqueue_failed",
    "prediction_timeout",
    "execution_timeout",
    "unknown_fail_closed",
}


@dataclass(frozen=True)
class RiskClampInput:
    odds_snapshot: Mapping[str, Any] = field(default_factory=dict)
    feature_snapshot: Mapping[str, Any] = field(default_factory=dict)
    prediction_snapshot: Mapping[str, Any] = field(default_factory=dict)
    calibration_state: Mapping[str, Any] = field(default_factory=dict)
    uncertainty_state: Mapping[str, Any] = field(default_factory=dict)
    bankroll_snapshot: Mapping[str, Any] = field(default_factory=dict)
    regime_state: Mapping[str, Any] = field(default_factory=dict)
    race_state: Mapping[str, Any] = field(default_factory=dict)
    clock_state: Mapping[str, Any] = field(default_factory=dict)
    exposure_snapshot: Mapping[str, Any] = field(default_factory=dict)
    policy_snapshot: Mapping[str, Any] = field(default_factory=dict)
    model_state: Mapping[str, Any] = field(default_factory=dict)
    sizing_proposal: Mapping[str, Any] = field(default_factory=dict)
    odds_freshness_ms: float | None = None
    feature_age_ms: float | None = None


@dataclass(frozen=True)
class RiskClampResult:
    allowed: bool
    decision: str
    max_stake: float
    risk_multiplier: float
    reason: str
    risk_limits_hash: str
    diagnostics: dict[str, Any]


class RiskClamp:
    def evaluate(self, risk_input: RiskClampInput) -> RiskClampResult:
        try:
            risk_limits_hash = self._risk_limits_hash(risk_input)
            reason = self._first_no_bet_reason(risk_input)
            max_stake = self._positive_float(risk_input.sizing_proposal.get("max_stake"))
            if max_stake <= 0:
                max_stake = self._positive_float(risk_input.sizing_proposal.get("amount"))
            risk_multiplier = self._bounded_multiplier(
                risk_input.sizing_proposal.get("risk_multiplier", 1.0)
            )

            if reason is not None:
                return self._result(False, 0.0, 0.0, reason, risk_limits_hash, risk_input)

            if max_stake <= 0 or risk_multiplier <= 0:
                return self._result(
                    False,
                    0.0,
                    0.0,
                    "risk_limits_invalid",
                    risk_limits_hash,
                    risk_input,
                )

            return self._result(
                True,
                max_stake,
                risk_multiplier,
                "risk_clamp_allowed",
                risk_limits_hash,
                risk_input,
            )
        except Exception:
            return RiskClampResult(
                allowed=False,
                decision="NO_BET",
                max_stake=0.0,
                risk_multiplier=0.0,
                reason="unknown_fail_closed",
                risk_limits_hash=self._hash_payload({"error": "unknown_fail_closed"}),
                diagnostics={},
            )

    def _first_no_bet_reason(self, risk_input: RiskClampInput) -> str | None:
        odds = risk_input.odds_snapshot or {}
        features = risk_input.feature_snapshot or {}
        calibration = risk_input.calibration_state or {}
        uncertainty = risk_input.uncertainty_state or {}
        bankroll = risk_input.bankroll_snapshot or {}
        race = risk_input.race_state or {}
        clock = risk_input.clock_state or {}
        policy = risk_input.policy_snapshot or {}
        model = risk_input.model_state or {}
        proposal = risk_input.sizing_proposal or {}

        if self._truthy(odds, "missing") or self._truthy(odds, "missing_odds"):
            return "missing_odds"
        if risk_input.odds_freshness_ms is None or self._truthy(odds, "stale"):
            return "stale_odds"
        max_odds_age_ms = self._positive_float(policy.get("max_odds_age_ms"), default=2_000.0)
        if float(risk_input.odds_freshness_ms) > max_odds_age_ms:
            return "stale_odds"

        if self._truthy(features, "missing") or self._truthy(features, "missing_features"):
            return "missing_features"
        if self._truthy(features, "stale"):
            return "stale_features"
        max_feature_age_ms = self._positive_float(policy.get("max_feature_age_ms"), default=5_000.0)
        if risk_input.feature_age_ms is not None and float(risk_input.feature_age_ms) > max_feature_age_ms:
            return "stale_features"

        if self._truthy(race, "cancelled") or self._truthy(race, "race_cancelled"):
            return "race_cancelled"

        max_clock_skew_ms = self._positive_float(policy.get("max_clock_skew_ms"), default=1_000.0)
        if self._truthy(clock, "skew") or abs(self._float(clock.get("clock_skew_ms"))) > max_clock_skew_ms:
            return "clock_skew"

        if self._truthy(calibration, "expired") or self._truthy(calibration, "stale"):
            return "calibration_expired"
        if self._truthy(calibration, "invalid"):
            return "calibration_invalid"

        if self._truthy(bankroll, "uncertain"):
            return "bankroll_uncertain"
        if self._truthy(bankroll, "stale"):
            return "bankroll_stale"

        if self._truthy(model, "hash_mismatch") or self._hash_mismatch(model):
            return "model_hash_mismatch"
        if self._truthy(policy, "hash_mismatch") or self._hash_mismatch(policy):
            return "policy_hash_mismatch"

        no_bet_reason = proposal.get("no_bet_reason") or proposal.get("reason")
        if no_bet_reason and str(no_bet_reason) != "OK":
            return self._normalize_no_bet_reason(str(no_bet_reason))

        if proposal.get("allowed") is False or proposal.get("should_bet") is False:
            proposal_reason = str(proposal.get("reason", "risk_limits_invalid"))
            if proposal_reason == "OK":
                proposal_reason = "risk_limits_invalid"
            return self._normalize_no_bet_reason(proposal_reason)

        return None

    def _result(
        self,
        allowed: bool,
        max_stake: float,
        risk_multiplier: float,
        reason: str,
        risk_limits_hash: str,
        risk_input: RiskClampInput,
    ) -> RiskClampResult:
        return RiskClampResult(
            allowed=bool(allowed),
            decision="BET" if allowed else "NO_BET",
            max_stake=float(max_stake),
            risk_multiplier=float(risk_multiplier),
            reason=reason,
            risk_limits_hash=risk_limits_hash,
            diagnostics={
                "odds_freshness_ms": risk_input.odds_freshness_ms,
                "feature_age_ms": risk_input.feature_age_ms,
            },
        )

    def _risk_limits_hash(self, risk_input: RiskClampInput) -> str:
        payload = {
            "policy_snapshot": risk_input.policy_snapshot,
            "model_state": risk_input.model_state,
            "calibration_state": risk_input.calibration_state,
            "bankroll_snapshot": risk_input.bankroll_snapshot,
            "exposure_snapshot": risk_input.exposure_snapshot,
            "sizing_proposal": risk_input.sizing_proposal,
        }
        return self._hash_payload(payload)

    def _hash_payload(self, payload: Mapping[str, Any]) -> str:
        serialized = json.dumps(
            self._json_safe(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_safe(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _truthy(self, payload: Mapping[str, Any], key: str) -> bool:
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(value)

    def _float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _positive_float(self, value: Any, default: float = 0.0) -> float:
        return max(0.0, self._float(value, default=default))

    def _bounded_multiplier(self, value: Any) -> float:
        return max(0.0, min(1.0, self._float(value, default=1.0)))

    def _hash_mismatch(self, payload: Mapping[str, Any]) -> bool:
        expected = payload.get("expected_hash")
        active = payload.get("active_hash")
        if not expected or not active:
            return False
        return str(expected) != str(active)

    def _normalize_no_bet_reason(self, reason: str) -> str:
        normalized = reason.strip().lower()
        aliases = {
            "high_uncertainty": "calibration_invalid",
            "low_edge_quality": "risk_limits_invalid",
            "insufficient_edge": "risk_limits_invalid",
            "missing_risk_sizer": "risk_limits_invalid",
            "risk_sizing_failed": "risk_limits_invalid",
            "risk_rejected": "risk_limits_invalid",
            "timeout": "execution_timeout",
            "api_timeout": "execution_timeout",
            "api call exceeded": "execution_timeout",
            "prediction timed out": "prediction_timeout",
            "retry_budget": "retry_budget_exceeded",
            "retry_budget_exceeded": "retry_budget_exceeded",
            "consecutive_timeouts": "retry_budget_exceeded",
            "auth": "session_expired",
            "unauthorized": "session_expired",
            "session_expired": "session_expired",
            "forbidden": "ip_blocked",
            "ip_blocked": "ip_blocked",
            "odds_spike": "odds_spike",
            "audit_failed": "audit_enqueue_failed",
            "audit_enqueue_failed": "audit_enqueue_failed",
        }
        normalized = aliases.get(normalized, normalized)
        if "timeout" in normalized and "prediction" in normalized:
            return "prediction_timeout"
        if "timeout" in normalized:
            return "execution_timeout"
        if "retry" in normalized and "budget" in normalized:
            return "retry_budget_exceeded"
        if "session" in normalized and ("expired" in normalized or "auth" in normalized):
            return "session_expired"
        if "unauthorized" in normalized or "auth" in normalized:
            return "session_expired"
        if "ip" in normalized and "block" in normalized:
            return "ip_blocked"
        if "forbidden" in normalized:
            return "ip_blocked"
        if "odds" in normalized and "spike" in normalized:
            return "odds_spike"
        if "audit" in normalized and ("enqueue" in normalized or "failed" in normalized):
            return "audit_enqueue_failed"
        return normalized if normalized in VALID_NO_BET_REASONS else "unknown_fail_closed"
