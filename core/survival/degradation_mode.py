from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config" / "degradation_mode.yaml"
PRODUCTION_SAFE_BET_TYPES = ("win", "place", "wide")


def _bet_type_helpers():
    from core.betting.bet_types import default_registry, normalize_bet_type

    return default_registry, normalize_bet_type


class DegradationMode(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    DANGER = "DANGER"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class DegradationSignals:
    data_quality_score: float
    missing_odds_rate: float
    stale_odds_rate: float
    missing_features_rate: float
    loss_streak: int
    drawdown_pct: float
    latency_p99_ms: float
    latency_regression_rate: float
    drift_gap50: float
    feature_psi_max: float
    odds_distribution_psi: float
    timeout_rate: float
    shadow_only_violation_count: int = 0
    disabled_bet_type_candidate_count: int = 0

    @classmethod
    def normal(cls) -> "DegradationSignals":
        return cls(
            data_quality_score=1.0,
            missing_odds_rate=0.0,
            stale_odds_rate=0.0,
            missing_features_rate=0.0,
            loss_streak=0,
            drawdown_pct=0.0,
            latency_p99_ms=0.0,
            latency_regression_rate=0.0,
            drift_gap50=0.0,
            feature_psi_max=0.0,
            odds_distribution_psi=0.0,
            timeout_rate=0.0,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "DegradationSignals":
        payload = payload or {}
        defaults = asdict(cls.normal())
        values = {key: payload.get(key, default) for key, default in defaults.items()}
        return cls(
            data_quality_score=_float(values["data_quality_score"]),
            missing_odds_rate=_float(values["missing_odds_rate"]),
            stale_odds_rate=_float(values["stale_odds_rate"]),
            missing_features_rate=_float(values["missing_features_rate"]),
            loss_streak=int(_float(values["loss_streak"])),
            drawdown_pct=_float(values["drawdown_pct"]),
            latency_p99_ms=_float(values["latency_p99_ms"]),
            latency_regression_rate=_float(values["latency_regression_rate"]),
            drift_gap50=_float(values["drift_gap50"]),
            feature_psi_max=_float(values["feature_psi_max"]),
            odds_distribution_psi=_float(values["odds_distribution_psi"]),
            timeout_rate=_float(values["timeout_rate"]),
            shadow_only_violation_count=int(_float(values["shadow_only_violation_count"])),
            disabled_bet_type_candidate_count=int(_float(values["disabled_bet_type_candidate_count"])),
        )


@dataclass(frozen=True)
class DegradationDecision:
    mode: str
    allowed_bet_types: list[str]
    stake_multiplier: float
    coverage_lower_bound: float
    coverage_upper_bound: float
    max_race_exposure_multiplier: float
    force_no_bet: bool
    reasons: list[str]
    requires_operator_ack: bool
    fail_closed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DegradationPolicy:
    thresholds: dict[str, dict[str, float]]
    decisions: dict[str, DegradationDecision]

    @classmethod
    def default(cls) -> "DegradationPolicy":
        return load_degradation_policy(DEFAULT_CONFIG_PATH)

    def template(self, mode: DegradationMode, reasons: list[str]) -> DegradationDecision:
        base = self.decisions[mode.value.lower()]
        return DegradationDecision(
            mode=mode.value,
            allowed_bet_types=list(base.allowed_bet_types),
            stake_multiplier=float(base.stake_multiplier),
            coverage_lower_bound=float(base.coverage_lower_bound),
            coverage_upper_bound=float(base.coverage_upper_bound),
            max_race_exposure_multiplier=float(base.max_race_exposure_multiplier),
            force_no_bet=bool(base.force_no_bet),
            reasons=list(reasons),
            requires_operator_ack=bool(base.requires_operator_ack),
            fail_closed=bool(base.fail_closed),
        )


def load_degradation_policy(path: Path = DEFAULT_CONFIG_PATH) -> DegradationPolicy:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_thresholds = payload.get("thresholds") or {}
    raw_decisions = payload.get("decisions") or {}
    decisions: dict[str, DegradationDecision] = {}
    for mode in DegradationMode:
        key = mode.value.lower()
        raw = raw_decisions.get(key) or {}
        decisions[key] = _decision_from_config(mode, raw)
    return DegradationPolicy(thresholds=dict(raw_thresholds), decisions=decisions)


_DEFAULT_POLICY: DegradationPolicy | None = None


def default_policy() -> DegradationPolicy:
    global _DEFAULT_POLICY
    if _DEFAULT_POLICY is None:
        _DEFAULT_POLICY = load_degradation_policy(DEFAULT_CONFIG_PATH)
    return _DEFAULT_POLICY


def evaluate_degradation(
    signals: DegradationSignals | Mapping[str, Any] | None,
    *,
    policy: DegradationPolicy | None = None,
) -> DegradationDecision:
    policy = policy or default_policy()
    normalized = signals if isinstance(signals, DegradationSignals) else DegradationSignals.from_mapping(signals)

    critical_reasons = _reasons(normalized, policy.thresholds.get("critical", {}))
    if critical_reasons:
        return _stricten_decision(policy.template(DegradationMode.CRITICAL, critical_reasons))

    danger_reasons = _reasons(normalized, policy.thresholds.get("danger", {}))
    if danger_reasons:
        return _stricten_decision(policy.template(DegradationMode.DANGER, danger_reasons))

    warning_reasons = _reasons(normalized, policy.thresholds.get("warning", {}))
    if warning_reasons:
        return _stricten_decision(policy.template(DegradationMode.WARNING, warning_reasons))

    return _stricten_decision(policy.template(DegradationMode.NORMAL, []))


def apply_degradation_to_bet(
    *,
    bet_type: str,
    stake: float,
    decision: DegradationDecision,
) -> tuple[bool, float, str | None]:
    default_registry, normalize_bet_type = _bet_type_helpers()
    normalized = normalize_bet_type(bet_type)
    registry = default_registry()
    config = registry.get(normalized)
    if decision.force_no_bet:
        return False, 0.0, "degradation_force_no_bet"
    if not config.enabled:
        return False, 0.0, "disabled_bet_type_execution_rejected"
    if config.shadow_only:
        return False, 0.0, "shadow_only_execution_rejected"
    if not config.production_candidate:
        return False, 0.0, "production_candidate_false_execution_rejected"
    if normalized not in set(decision.allowed_bet_types):
        return False, 0.0, "degradation_bet_type_excluded"
    adjusted = max(0.0, float(stake) * float(decision.stake_multiplier))
    return adjusted > 0.0, adjusted, None if adjusted > 0.0 else "degradation_zero_stake"


def limit_candidates_by_degradation(
    candidates: Iterable[Any],
    decision: DegradationDecision,
) -> list[Any]:
    items = list(candidates)
    if not items or decision.force_no_bet:
        return []
    upper = max(0.0, min(1.0, float(decision.coverage_upper_bound)))
    if upper <= 0.0:
        return []
    keep = max(1, int(len(items) * upper))
    return items[:keep]


def decision_from_payload(payload: Mapping[str, Any] | None) -> DegradationDecision:
    payload = payload or {}
    mode = str(payload.get("mode") or payload.get("degradation_mode") or DegradationMode.NORMAL.value)
    return DegradationDecision(
        mode=mode,
        allowed_bet_types=list(payload.get("allowed_bet_types") or payload.get("degradation_allowed_bet_types") or PRODUCTION_SAFE_BET_TYPES),
        stake_multiplier=_float(payload.get("stake_multiplier", payload.get("degradation_stake_multiplier", 1.0))),
        coverage_lower_bound=_float(payload.get("coverage_lower_bound", 0.05)),
        coverage_upper_bound=_float(payload.get("coverage_upper_bound", 0.30)),
        max_race_exposure_multiplier=_float(payload.get("max_race_exposure_multiplier", 1.0)),
        force_no_bet=_bool(payload.get("force_no_bet", payload.get("degradation_force_no_bet", False))),
        reasons=list(payload.get("reasons") or payload.get("degradation_reasons") or []),
        requires_operator_ack=_bool(payload.get("requires_operator_ack", False)),
        fail_closed=_bool(payload.get("fail_closed", False)),
    )


def encode_reasons(reasons: Iterable[str]) -> str:
    return json.dumps(list(reasons), ensure_ascii=False)


def _decision_from_config(mode: DegradationMode, raw: Mapping[str, Any]) -> DegradationDecision:
    return DegradationDecision(
        mode=mode.value,
        allowed_bet_types=_safe_allowed_bet_types(raw.get("allowed_bet_types") or []),
        stake_multiplier=_float(raw.get("stake_multiplier", 0.0)),
        coverage_lower_bound=_float(raw.get("coverage_lower_bound", 0.0)),
        coverage_upper_bound=_float(raw.get("coverage_upper_bound", 0.0)),
        max_race_exposure_multiplier=_float(raw.get("max_race_exposure_multiplier", 0.0)),
        force_no_bet=_bool(raw.get("force_no_bet", True)),
        reasons=[],
        requires_operator_ack=_bool(raw.get("requires_operator_ack", mode in {DegradationMode.DANGER, DegradationMode.CRITICAL})),
        fail_closed=_bool(raw.get("fail_closed", mode == DegradationMode.CRITICAL)),
    )


def _stricten_decision(decision: DegradationDecision) -> DegradationDecision:
    allowed = _safe_allowed_bet_types(decision.allowed_bet_types)
    if decision.mode == DegradationMode.DANGER.value:
        allowed = [bet_type for bet_type in allowed if bet_type in {"win", "place"}]
    if decision.mode == DegradationMode.CRITICAL.value or decision.force_no_bet:
        allowed = []
    return DegradationDecision(
        mode=decision.mode,
        allowed_bet_types=allowed,
        stake_multiplier=max(0.0, min(1.0, float(decision.stake_multiplier))),
        coverage_lower_bound=max(0.0, min(1.0, float(decision.coverage_lower_bound))),
        coverage_upper_bound=max(0.0, min(1.0, float(decision.coverage_upper_bound))),
        max_race_exposure_multiplier=max(0.0, min(1.0, float(decision.max_race_exposure_multiplier))),
        force_no_bet=bool(decision.force_no_bet or decision.mode == DegradationMode.CRITICAL.value),
        reasons=list(decision.reasons),
        requires_operator_ack=bool(decision.requires_operator_ack or decision.mode in {DegradationMode.DANGER.value, DegradationMode.CRITICAL.value}),
        fail_closed=bool(decision.fail_closed or decision.mode == DegradationMode.CRITICAL.value),
    )


def _safe_allowed_bet_types(values: Iterable[Any]) -> list[str]:
    default_registry, normalize_bet_type = _bet_type_helpers()
    registry = default_registry()
    allowed: list[str] = []
    for value in values:
        try:
            bet_type = normalize_bet_type(str(value))
            config = registry.get(bet_type)
        except ValueError:
            continue
        if config.enabled and config.production_candidate and not config.shadow_only and bet_type in PRODUCTION_SAFE_BET_TYPES:
            allowed.append(bet_type)
    return [bet_type for bet_type in PRODUCTION_SAFE_BET_TYPES if bet_type in set(allowed)]


def _reasons(signals: DegradationSignals, thresholds: Mapping[str, Any]) -> list[str]:
    values = asdict(signals)
    reasons: list[str] = []
    for key, threshold in thresholds.items():
        if key.endswith("_lt"):
            field = key[:-3]
            if _float(values.get(field)) < _float(threshold):
                reasons.append(f"{field} < {threshold}")
        elif key.endswith("_gte"):
            field = key[:-4]
            if _float(values.get(field)) >= _float(threshold):
                reasons.append(f"{field} >= {threshold}")
        elif key.endswith("_gt"):
            field = key[:-3]
            if _float(values.get(field)) > _float(threshold):
                reasons.append(f"{field} > {threshold}")
    return reasons


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
