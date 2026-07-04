from __future__ import annotations

import csv
import json
import hashlib
import concurrent.futures
import logging
import os
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from core.betting.bet_types import (
    default_registry,
    legs_to_json,
    normalize_legacy_win_record,
    parse_legs,
)
from core.betting.risk_clamp import RiskClamp, RiskClampInput
from core.circuit_breaker import SharedCircuitBreaker
from core.survival.degradation_mode import decision_from_payload, encode_reasons
from core.execution.odds_contract import (
    decision_probability,
    fill_expected_value,
    market_odds_at_decision,
    pre_bet_expected_value,
    slippage_pct,
)
from schemas.audit_event import build_audit_event


logger = logging.getLogger(__name__)

DEFAULT_DECISION_LOG_PATH = "logs/decisions.jsonl"


def _parse_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _read_safe_mode_from_settings(settings_path: Path, default: bool = True) -> bool:
    if not settings_path.exists():
        return default

    try:
        for raw_line in settings_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue

            key, value = line.split(":", 1)
            normalized_key = key.strip().lower()
            if normalized_key in {"safe_mode", "safe mode"}:
                return _parse_bool(value.strip().strip('"\''), default=default)
    except Exception:
        return default

    return default


def _read_shadow_mode_from_settings(settings_path: Path, default: bool = False) -> bool:
    if not settings_path.exists():
        return default

    try:
        for raw_line in settings_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue

            key, value = line.split(":", 1)
            normalized_key = key.strip().lower()
            if normalized_key in {"shadow_mode", "shadow mode"}:
                return _parse_bool(value.strip().strip('"\''), default=default)
    except Exception:
        return default

    return default


@dataclass
class BetExecutorState:
    safe_mode: bool
    shadow_mode: bool = False
    emergency: bool = False
    standby: bool = False
    reason: Optional[str] = None
    timeout_failures: int = 0
    auth_failures: int = 0


class BetExecutor:
    """Bet execution facade with append-only JSONL audit logging.

    - SAFE_MODE=True forces every stake to the minimum lot (100 yen).
    - Real API clients should expose `place_bet(bet_info) -> dict` or
      `execute_vote(bet_info) -> dict`. The returned dict may include
      status/submitted/confirmed_odds/provider/error.
    - Emergency shutdown can block further execution on repeated API failures
      or on external system signals.
    - CSV output is report-only compatibility; JSONL is the runtime authority.
    """

    def __init__(
        self,
        risk_manager,
        log_path: Optional[str] = None,
        *,
        decision_log_path: str = DEFAULT_DECISION_LOG_PATH,
        csv_report_path: Optional[str] = None,
        safe_mode: Optional[bool] = None,
        shadow_mode: Optional[bool] = None,
        api_client: Any = None,
        circuit_breaker: Optional[SharedCircuitBreaker] = None,
        odds_confirmer: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
        on_settle: Optional[Callable[[Dict[str, Any]], None]] = None,
        emergency_sources: Optional[Iterable[Any]] = None,
        settings_path: Optional[str] = None,
        minimum_lot: int = 100,
        max_consecutive_timeouts: int = 3,
        max_consecutive_auth_errors: int = 2,
        api_timeout_seconds: float = 0.5,
        model_path: str = "models/predictor.pkl",
        calibrator_state_path: str = "models/calibration_model.pkl",
        calibration_model_path: Optional[str] = None,
        risk_clamp: Optional[RiskClamp] = None,
    ):

        self.risk_manager = risk_manager
        if csv_report_path is None and log_path is not None:
            csv_report_path = log_path
            if decision_log_path == DEFAULT_DECISION_LOG_PATH:
                decision_log_path = str(Path(log_path).parent / "decisions.jsonl")

        self.csv_report_path = Path(csv_report_path) if csv_report_path else None
        self.log_path = self.csv_report_path
        self.jsonl_path = Path(decision_log_path)
        self.api_client = api_client
        self.circuit_breaker = circuit_breaker
        self.odds_confirmer = odds_confirmer
        self.on_settle = on_settle
        self.minimum_lot = int(minimum_lot)
        self.max_consecutive_timeouts = int(max_consecutive_timeouts)
        self.max_consecutive_auth_errors = int(max_consecutive_auth_errors)
        self.api_timeout_seconds = float(api_timeout_seconds)
        self.model_path = self._resolve_runtime_path(model_path)
        self.calibration_model_path = Path(calibration_model_path or calibrator_state_path)
        self.calibration_model_path = self._resolve_runtime_path(self.calibration_model_path)
        self.risk_clamp = risk_clamp or RiskClamp()
        self._emergency_sources = list(emergency_sources or [])
        self._state_lock = threading.RLock()
        self._settings_path = self._resolve_settings_path(settings_path)
        self._model_pkl_sha256 = self._file_sha256(self.model_path, missing="unfitted")
        self._model_version_value = (
            self._model_pkl_sha256[:16]
            if self._model_pkl_sha256 not in {"unfitted", "unavailable"}
            else self._model_pkl_sha256
        )
        self._calibration_hash_value = self._file_sha256(
            self.calibration_model_path,
            missing="unfitted",
        )
        self._calibration_last_refit_at_value = self._file_mtime_iso(
            self.calibration_model_path,
            missing="unfitted",
        )
        self._api_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="bet-executor-api",
        )

        resolved_safe_mode = safe_mode
        if resolved_safe_mode is None:
            resolved_safe_mode = _parse_bool(
                os.getenv("SAFE_MODE"),
                default=_read_safe_mode_from_settings(self._settings_path, default=True),
            )

        resolved_shadow_mode = shadow_mode
        if resolved_shadow_mode is None:
            resolved_shadow_mode = _parse_bool(
                os.getenv("SHADOW_MODE"),
                default=_read_shadow_mode_from_settings(self._settings_path, default=False),
            )

        self._state = BetExecutorState(
            safe_mode=bool(resolved_safe_mode),
            shadow_mode=bool(resolved_shadow_mode),
        )

        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_jsonl_hash = self._load_last_jsonl_hash()
        if self.csv_report_path is not None:
            self.csv_report_path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize_csv()

    def _resolve_settings_path(self, settings_path: Optional[str]) -> Path:
        if settings_path is not None:
            return Path(settings_path)
        return Path(__file__).resolve().parents[2] / "config" / "settings.yaml"

    def _resolve_runtime_path(self, path: Any) -> Path:
        resolved = Path(path)
        if resolved.is_absolute():
            return resolved
        return Path(__file__).resolve().parents[2] / resolved

    def _file_sha256(self, path: Path, *, missing: str) -> str:
        if not path.exists() or path.stat().st_size == 0:
            return missing
        try:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except Exception:
            return "unavailable"

    def _file_mtime_iso(self, path: Path, *, missing: str) -> str:
        if not path.exists() or path.stat().st_size == 0:
            return missing
        try:
            return datetime.utcfromtimestamp(path.stat().st_mtime).isoformat()
        except Exception:
            return "unavailable"

    def _csv_headers(self) -> list[str]:
        return [
            "timestamp",
            "race_id",
            "selection",
            "bet_type",
            "legs",
            "ordered",
            "shadow_only",
            "production_candidate",
            "max_combinations_per_race",
            "max_race_exposure_share",
            "degradation_mode",
            "degradation_reasons",
            "degradation_stake_multiplier",
            "degradation_allowed_bet_types",
            "degradation_force_no_bet",
            "probability",
            "odds",
            "predicted_odds",
            "confirmed_odds",
            "slippage_pct",
            "edge",
            "expected_value",
            "expected_value_per_unit",
            "calibrated_probability",
            "stake",
            "mode",
            "api_status",
            "api_error",
            "hit",
            "payout",
            "profit",
            "bankroll",
            "drawdown",
            "risk_multiplier",
            "lose_streak",
            "win_streak",
            "race_risk_used",
            "model_version",
            "model_pkl_sha256",
            "calibration_hash",
            "calibration_last_refit_at",
            "odds_snapshot_ts",
            "risk_limits_hash",
            "risk_clamp_reason",
            "shutdown_state",
            "shutdown_reason",
        ]

    def _initialize_csv(self):
        if self.csv_report_path is None:
            return

        headers = self._csv_headers()

        if not self.csv_report_path.exists():
            with open(self.csv_report_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(headers)
            return

        with open(self.csv_report_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        if not lines:
            with open(self.csv_report_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(headers)
            return

        first_row = lines[0].split(",")
        if first_row == headers:
            return

        existing_rows = list(csv.DictReader(lines)) if len(lines) > 1 else []
        with open(self.csv_report_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in existing_rows:
                writer.writerow({key: row.get(key, "") for key in headers})

    def register_emergency_source(self, source: Any) -> None:
        self._emergency_sources.append(source)

    def is_blocked(self) -> bool:
        if self.circuit_breaker is not None and self.circuit_breaker.is_open():
            return True
        with self._state_lock:
            return self._state.emergency or self._state.standby

    def emergency_shutdown(
        self,
        reason: str,
        *,
        source: Optional[str] = None,
        error: Optional[BaseException] = None,
        pause_only: bool = True,
    ) -> Dict[str, Any]:
        with self._state_lock:
            self._state.emergency = True
            self._state.standby = bool(pause_only)
            self._state.reason = reason
        if self.circuit_breaker is not None:
            self.circuit_breaker.force_open(reason)

        message = f"[EMERGENCY SHUTDOWN] reason={reason} source={source} pause_only={pause_only}"
        if error is not None:
            message += f" error={error}"
        logger.critical(message)
        logger.critical(message)

        return {
            "blocked": True,
            "state": "STANDBY" if pause_only else "SHUTDOWN",
            "reason": reason,
            "source": source,
        }

    def resume_from_emergency(self) -> None:
        with self._state_lock:
            self._state.emergency = False
            self._state.standby = False
            self._state.reason = None
            self._state.timeout_failures = 0
            self._state.auth_failures = 0
        if self.circuit_breaker is not None:
            self.circuit_breaker.record_success()
        logger.info("BetExecutor emergency state cleared")

    def _current_risk_snapshot(self) -> Dict[str, Any]:
        status = {}
        if hasattr(self.risk_manager, "status") and callable(self.risk_manager.status):
            try:
                status = dict(self.risk_manager.status() or {})
            except Exception as exc:
                logger.warning("risk_manager.status() failed: %s", exc)

        return {
            "bankroll": status.get("bankroll", getattr(self.risk_manager, "bankroll", 0.0)),
            "drawdown": status.get("drawdown", 0.0),
            "risk_multiplier": status.get("risk_multiplier", 1.0),
            "lose_streak": status.get("lose_streak", 0),
            "win_streak": status.get("win_streak", 0),
            "race_risk_used": status.get("race_risk_used", 0.0),
        }

    def _should_block_from_source(self, source: Any) -> Optional[str]:
        if source is None:
            return None

        if callable(source):
            try:
                result = source()
                if isinstance(result, tuple):
                    active = bool(result[0])
                    reason = str(result[1]) if len(result) > 1 and result[1] else "EMERGENCY_SOURCE"
                    return reason if active else None
                if bool(result):
                    return "EMERGENCY_SOURCE"
            except Exception as exc:
                logger.warning("Emergency source callable failed: %s", exc)
                return "EMERGENCY_SOURCE_ERROR"

        if getattr(source, "destroyed", False):
            return getattr(source, "last_reason", None) or "DESTROYED"
        if getattr(source, "emergency_mode", False):
            return "EMERGENCY_MODE"
        if getattr(source, "shutdown", False):
            return "SHUTDOWN"

        status = None
        if hasattr(source, "status") and callable(source.status):
            try:
                status = source.status()
            except Exception:
                status = None

        if isinstance(status, dict):
            if status.get("destroyed"):
                return status.get("last_reason") or "DESTROYED"
            if status.get("shutdown"):
                return status.get("reason") or "SHUTDOWN"
            if status.get("emergency_mode"):
                return status.get("reason") or "EMERGENCY_MODE"

        if getattr(source, "should_shutdown", None):
            try:
                if source.should_shutdown():
                    return "SHOULD_SHUTDOWN"
            except Exception as exc:
                logger.warning("Emergency source should_shutdown() failed: %s", exc)

        return None

    def _poll_external_emergency(self) -> Optional[str]:
        for source in self._emergency_sources:
            reason = self._should_block_from_source(source)
            if reason:
                return reason

        reason = self._should_block_from_source(self.risk_manager)
        if reason:
            return reason

        return None

    def _normalize_stake(self, requested_stake: Any) -> int:
        stake = int(round(float(requested_stake or 0.0)))
        if self._state.safe_mode:
            return self.minimum_lot
        return max(stake, 0)

    def _bet_type_context(self, decision: Any) -> Dict[str, Any]:
        registry = default_registry()
        legs = getattr(decision, "legs", None)
        if legs in (None, (), [], ""):
            legs = [str(getattr(decision, "selection_id", "") or getattr(decision, "selection", "")).strip()]
        if isinstance(legs, str):
            legs = parse_legs(legs)
        raw = {
            "race_id": getattr(decision, "race_id", ""),
            "selection": getattr(decision, "selection", ""),
            "selection_id": getattr(decision, "selection_id", ""),
            "bet_type": getattr(decision, "bet_type", "win"),
            "legs": list(legs),
            "odds": getattr(decision, "odds", 0.0),
            "stake": getattr(decision, "bet_size", 0.0),
            "source": getattr(decision, "source", ""),
        }
        normalized = normalize_legacy_win_record(raw, registry=registry)
        return normalized

    def _execution_bet_type_block_reason(self, bet_info: Dict[str, Any]) -> str | None:
        degradation = decision_from_payload(bet_info)
        if degradation.force_no_bet:
            return "degradation_force_no_bet"
        bet_type = str(bet_info.get("bet_type") or "")
        try:
            config = default_registry().get(bet_type)
        except ValueError:
            return "production_execution_unknown_bet_type"
        if not config.enabled:
            return "disabled_bet_type_execution_rejected"
        if config.shadow_only:
            return "shadow_only_execution_rejected"
        if not config.production_candidate:
            return "production_candidate_false_execution_rejected"
        if bet_type not in set(degradation.allowed_bet_types):
            return "degradation_bet_type_excluded"
        return None

    def _execution_mode_label(self) -> str:
        if self._state.shadow_mode:
            return "SHADOW_MODE"
        if self._state.safe_mode:
            return "SAFE_MODE"
        return "LIVE_MODE"

    def _build_bet_info(self, decision, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        bet_type_context = self._bet_type_context(decision)
        stake = self._normalize_stake(decision.bet_size)
        predicted_odds = round(market_odds_at_decision(decision), 4)
        probability = decision_probability(decision)
        expected_value = round(pre_bet_expected_value(decision), 6)
        calibrated = getattr(decision, "calibrated_probability", None)
        calibrated_probability = (
            round(float(calibrated), 6) if calibrated is not None else round(probability, 6)
        )
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "race_id": decision.race_id,
            "selection": decision.selection,
            "bet_type": bet_type_context["bet_type"],
            "legs": list(bet_type_context["legs"]),
            "ordered": bool(bet_type_context["ordered"]),
            "shadow_only": bool(bet_type_context["shadow_only"]),
            "production_candidate": bool(bet_type_context["production_candidate"]),
            "max_combinations_per_race": int(bet_type_context["max_combinations_per_race"]),
            "max_race_exposure_share": float(bet_type_context["max_race_exposure_share"]),
            "degradation_mode": str(getattr(decision, "degradation_mode", "NORMAL") or "NORMAL"),
            "degradation_reasons": list(getattr(decision, "degradation_reasons", ()) or ()),
            "degradation_stake_multiplier": float(getattr(decision, "degradation_stake_multiplier", 1.0) or 1.0),
            "degradation_allowed_bet_types": list(getattr(decision, "degradation_allowed_bet_types", ("win", "place", "wide")) or ()),
            "degradation_force_no_bet": bool(getattr(decision, "degradation_force_no_bet", False)),
            "probability": round(probability, 6),
            "odds": predicted_odds,
            "predicted_odds": predicted_odds,
            "confirmed_odds": predicted_odds,
            "slippage_pct": 0.0,
            "edge": round(float(decision.edge), 6),
            "expected_value": expected_value,
            "expected_value_per_unit": expected_value,
            "calibrated_probability": calibrated_probability,
            "stake": stake,
            "mode": self._execution_mode_label(),
            "bankroll": snapshot["bankroll"],
            "drawdown": snapshot["drawdown"],
            "risk_multiplier": snapshot["risk_multiplier"],
            "lose_streak": snapshot["lose_streak"],
            "win_streak": snapshot["win_streak"],
            "race_risk_used": snapshot["race_risk_used"],
            "model_version": self._model_version(),
            "model_hash": str(getattr(decision, "model_hash", "") or self._model_pkl_sha256),
            "model_pkl_sha256": self._model_pkl_sha256,
            "calibration_hash": self._calibration_hash(),
            "calibration_last_refit_at": self._calibration_last_refit_at(),
            "odds_snapshot_ts": self._odds_snapshot_ts(decision),
            "odds_snapshot_hash": str(getattr(decision, "odds_snapshot_hash", "") or ""),
            "feature_snapshot_hash": str(getattr(decision, "feature_snapshot_hash", "") or ""),
            "policy_hash": str(getattr(decision, "policy_hash", "") or ""),
            "bankroll_hash": self._bankroll_hash(snapshot),
        }

    def _bankroll_hash(self, snapshot: Dict[str, Any]) -> str:
        payload = {
            "bankroll": snapshot.get("bankroll"),
            "drawdown": snapshot.get("drawdown"),
            "race_risk_used": snapshot.get("race_risk_used"),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _model_version(self) -> str:
        return self._model_version_value

    def _calibration_hash(self) -> str:
        return self._calibration_hash_value

    def _calibration_last_refit_at(self) -> str:
        return self._calibration_last_refit_at_value

    def _odds_snapshot_ts(self, decision: Any) -> str:
        for name in ("odds_snapshot_ts", "provider_timestamp", "scraped_at", "fetched_at"):
            value = getattr(decision, name, None)
            if value not in (None, ""):
                return str(value)
        return ""

    def _decision_risk_clamp_input(
        self,
        decision: Any,
        snapshot: Dict[str, Any],
        bet_info: Dict[str, Any],
    ) -> RiskClampInput:
        odds_hash = str(getattr(decision, "odds_snapshot_hash", "") or "")
        feature_hash = str(getattr(decision, "feature_snapshot_hash", "") or "")
        policy_hash = str(getattr(decision, "policy_hash", "") or "")
        model_hash = str(getattr(decision, "model_hash", "") or "")
        risk_limits_hash = str(getattr(decision, "risk_limits_hash", "") or "")
        proof_allowed = bool(getattr(decision, "risk_clamp_allowed", False))
        proof_reason = str(getattr(decision, "risk_clamp_reason", "") or "")
        has_required_proof = bool(
            proof_allowed
            and risk_limits_hash
            and policy_hash
            and model_hash
            and odds_hash
            and feature_hash
        )

        proposal_reason = "OK" if has_required_proof else "risk_limits_invalid"
        return RiskClampInput(
            odds_snapshot={
                "present": bool(odds_hash),
                "missing": not bool(odds_hash),
                "hash": odds_hash,
            },
            feature_snapshot={
                "present": bool(feature_hash),
                "missing": not bool(feature_hash),
                "hash": feature_hash,
            },
            prediction_snapshot={
                "probability": bet_info.get("probability"),
                "expected_value": bet_info.get("expected_value"),
                "edge": bet_info.get("edge"),
            },
            calibration_state={
                "calibration_hash": self._calibration_hash(),
                "invalid": False,
            },
            uncertainty_state={
                "uncertainty_score": getattr(decision, "uncertainty_score", None),
                "edge_quality": getattr(decision, "edge_quality", None),
            },
            bankroll_snapshot={
                "bankroll": snapshot.get("bankroll"),
                "drawdown": snapshot.get("drawdown"),
                "uncertain": snapshot.get("bankroll") in (None, ""),
                "stale": False,
            },
            regime_state={},
            race_state={
                "race_id": getattr(decision, "race_id", ""),
                "race_cancelled": bool(getattr(decision, "race_cancelled", False)),
            },
            clock_state={"clock_skew_ms": float(getattr(decision, "clock_skew_ms", 0.0) or 0.0)},
            exposure_snapshot={"race_risk_used": snapshot.get("race_risk_used", 0.0)},
            policy_snapshot={
                "policy_hash": policy_hash or "missing_policy_hash",
                "expected_hash": policy_hash or "missing_policy_hash",
                "active_hash": policy_hash or "missing_policy_hash",
            },
            model_state={
                "model_hash": model_hash or "missing_model_hash",
                "expected_hash": model_hash or "missing_model_hash",
                "active_hash": model_hash or "missing_model_hash",
            },
            sizing_proposal={
                "allowed": has_required_proof,
                "max_stake": bet_info.get("stake", 0),
                "risk_multiplier": snapshot.get("risk_multiplier", 0.0),
                "reason": proposal_reason,
                "proof_reason": proof_reason,
                "proof_risk_limits_hash": risk_limits_hash,
            },
            odds_freshness_ms=0.0 if odds_hash else None,
            feature_age_ms=0.0 if feature_hash else None,
        )

    def _execute_real_vote(self, bet_info: Dict[str, Any]) -> Dict[str, Any]:
        """Placeholder for JRA IPAT / live-vote API integration.

        If no client is configured, this falls back to a dry-run response so the
        current CSV-only workflow stays intact until a concrete API adapter is
        supplied.
        """

        if not bet_info.get("risk_clamp_allowed"):
            return {
                "status": "blocked",
                "submitted": False,
                "provider": "risk_clamp",
                "error": "risk_clamp_required",
            }

        if self._state.shadow_mode:
            confirmed = None
            if self.odds_confirmer is not None:
                try:
                    confirmed = self._call_with_timeout(
                        self.odds_confirmer,
                        dict(bet_info),
                        timeout_seconds=self.api_timeout_seconds,
                    )
                except Exception as exc:
                    logger.warning("Shadow odds_confirmer failed: %s", exc)

            if confirmed is None:
                confirmed = bet_info["predicted_odds"]

            return {
                "status": "shadow",
                "submitted": False,
                "provider": "shadow",
                "confirmed_odds": confirmed,
                "request": dict(bet_info),
            }

        client = self.api_client
        if client is None:
            logger.info("No vote API client configured; storing dry-run execution.")
            return {
                "status": "dry_run",
                "submitted": False,
                "provider": "none",
                "request": dict(bet_info),
            }

        try:
            if callable(client):
                return self._call_with_timeout(
                    client,
                    bet_info,
                    timeout_seconds=self.api_timeout_seconds,
                )

            for method_name in ("execute_vote", "place_bet", "vote", "submit_vote"):
                method = getattr(client, method_name, None)
                if callable(method):
                    return self._call_with_timeout(
                        method,
                        bet_info,
                        timeout_seconds=self.api_timeout_seconds,
                    )

        except Exception:
            raise

        raise NotImplementedError(
            "Configured api_client does not expose a supported vote method"
        )

    def _call_with_timeout(
        self,
        func: Callable[..., Any],
        *args,
        timeout_seconds: float,
        **kwargs,
    ) -> Any:
        future = self._api_executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError(
                f"API call exceeded {timeout_seconds:.3f}s"
            ) from exc

    def _classify_api_error(self, error: BaseException) -> str:
        error_name = error.__class__.__name__.lower()
        message = str(error).lower()
        status_code = getattr(getattr(error, "response", None), "status_code", None)

        if isinstance(error, (TimeoutError, socket.timeout)):
            return "timeout"
        if "timeout" in error_name or "timeout" in message or "timed out" in message:
            return "timeout"
        if status_code == 401:
            return "session_expired"
        if status_code == 403:
            return "ip_blocked"
        if "ip" in message and "block" in message:
            return "ip_blocked"
        if "auth" in error_name or "unauthorized" in message or "session" in message:
            return "session_expired"
        if "forbidden" in message:
            return "ip_blocked"
        if "connection" in error_name or "network" in message:
            return "network"
        return "unexpected"

    def _register_failure(self, category: str, error: BaseException) -> Optional[Dict[str, Any]]:
        with self._state_lock:
            if category == "timeout":
                self._state.timeout_failures += 1
            elif category in {"session_expired", "ip_blocked"}:
                self._state.auth_failures += 1
            else:
                self._state.timeout_failures = 0
                self._state.auth_failures = 0

            timeout_hit = self._state.timeout_failures >= self.max_consecutive_timeouts
            auth_hit = self._state.auth_failures >= self.max_consecutive_auth_errors

        if timeout_hit:
            return self.emergency_shutdown(
                reason="retry_budget_exceeded",
                source="api",
                error=error,
                pause_only=True,
            )

        if auth_hit:
            reason = "ip_blocked" if category == "ip_blocked" else "session_expired"
            return self.emergency_shutdown(
                reason=reason,
                source="api",
                error=error,
                pause_only=True,
            )

        return None

    def _append_row(self, row: Dict[str, Any]):
        if self.csv_report_path is None:
            return

        # Legacy CSV append for derived report compatibility.
        try:
            with open(self.csv_report_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._csv_headers())
                writer.writerow({key: row.get(key, "") for key in self._csv_headers()})
        except Exception as exc:
            logger.warning("Failed to append CSV audit row: %s", exc)

    def _load_last_jsonl_hash(self) -> Optional[str]:
        if not self.jsonl_path.exists():
            return None
        try:
            with open(self.jsonl_path, "r", encoding="utf-8") as f:
                for line in reversed(f.read().splitlines()):
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                        return obj.get("entry_hash")
                    except Exception:
                        continue
        except Exception:
            return None
        return None

    def _append_jsonl_event(self, event_type: str, payload: Dict[str, Any]):
        with self._state_lock:
            previous_hash = self._last_jsonl_hash
            record = {
                "event": event_type,
                "timestamp": datetime.utcnow().isoformat(),
                "payload": payload,
                "previous_hash": previous_hash,
            }
            # canonical JSON
            canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            h = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            record["entry_hash"] = h

            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._last_jsonl_hash = h

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append_audit_event(self, event_type: str, race_id: str, payload: Dict[str, Any]):
        with self._state_lock:
            previous_hash = self._last_jsonl_hash
            event = build_audit_event(
                event_id=f"{race_id}:{event_type}:{datetime.now(timezone.utc).timestamp():.9f}",
                event_type=event_type,
                occurred_at_utc=self._utc_now(),
                race_id=str(race_id),
                payload=payload,
                previous_hash=previous_hash,
            )
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            self._last_jsonl_hash = event.entry_hash
            return event

    def _base_decision_payload(self, decision: Any, bet_info: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "decision_id": str(getattr(decision, "decision_id", "") or f"{bet_info['race_id']}:{bet_info['selection']}"),
            "race_id": bet_info["race_id"],
            "selection_id": str(getattr(decision, "selection_id", "") or bet_info["selection"]),
            "selection": bet_info["selection"],
            "bet_type": bet_info.get("bet_type", "win"),
            "legs": legs_to_json(bet_info.get("legs", [])),
            "ordered": bool(bet_info.get("ordered", False)),
            "shadow_only": bool(bet_info.get("shadow_only", False)),
            "production_candidate": bool(bet_info.get("production_candidate", True)),
            "max_combinations_per_race": bet_info.get("max_combinations_per_race"),
            "max_race_exposure_share": bet_info.get("max_race_exposure_share"),
            "degradation_mode": bet_info.get("degradation_mode", "NORMAL"),
            "degradation_reasons": encode_reasons(bet_info.get("degradation_reasons", [])),
            "degradation_stake_multiplier": bet_info.get("degradation_stake_multiplier", 1.0),
            "degradation_allowed_bet_types": list(bet_info.get("degradation_allowed_bet_types", [])),
            "degradation_force_no_bet": bool(bet_info.get("degradation_force_no_bet", False)),
            "decision_time_utc": self._utc_now(),
            "odds_snapshot_hash": bet_info.get("odds_snapshot_hash", ""),
            "feature_snapshot_hash": bet_info.get("feature_snapshot_hash", ""),
            "model_hash": bet_info.get("model_hash", ""),
            "model_version": bet_info.get("model_version", ""),
            "model_pkl_sha256": bet_info.get("model_pkl_sha256", ""),
            "calibration_hash": bet_info.get("calibration_hash", ""),
            "bankroll_hash": bet_info.get("bankroll_hash", ""),
            "policy_hash": bet_info.get("policy_hash", ""),
            "risk_limits_hash": bet_info.get("risk_limits_hash", ""),
            "probability": bet_info.get("probability"),
            "calibrated_probability": bet_info.get("calibrated_probability"),
            "odds": bet_info.get("odds"),
            "edge": bet_info.get("edge"),
            "expected_value": bet_info.get("expected_value"),
            "stake": bet_info.get("stake"),
            "execution_status": "SHADOW" if self._state.shadow_mode else "LIVE",
            "shadow_mode": bool(self._state.shadow_mode),
            "safe_mode": bool(self._state.safe_mode),
        }

    def _settlement_payload(self, decision: Any, snapshot: Dict[str, Any], hit: Any, profit: Any) -> Dict[str, Any]:
        return {
            "race_id": decision.race_id,
            "selection": decision.selection,
            "selection_id": str(getattr(decision, "selection_id", "") or decision.selection),
            "bet_type": getattr(decision, "bet_type", "win"),
            "legs": legs_to_json(getattr(decision, "legs", ()) or (decision.selection,)),
            "ordered": bool(getattr(decision, "ordered", False)),
            "shadow_only": bool(getattr(decision, "shadow_only", False)),
            "production_candidate": bool(getattr(decision, "production_candidate", True)),
            "max_combinations_per_race": getattr(decision, "max_combinations_per_race", 1),
            "max_race_exposure_share": getattr(decision, "max_race_exposure_share", 0.50),
            "degradation_mode": getattr(decision, "degradation_mode", "NORMAL"),
            "degradation_reasons": encode_reasons(getattr(decision, "degradation_reasons", ())),
            "degradation_stake_multiplier": getattr(decision, "degradation_stake_multiplier", 1.0),
            "degradation_allowed_bet_types": list(getattr(decision, "degradation_allowed_bet_types", ("win", "place", "wide"))),
            "degradation_force_no_bet": bool(getattr(decision, "degradation_force_no_bet", False)),
            "hit": int(hit),
            "stake": float(getattr(decision, "bet_size", 0.0) or 0.0),
            "payout": round(float(profit) + float(getattr(decision, "bet_size", 0.0) or 0.0), 2) if bool(hit) else 0.0,
            "profit": round(float(profit), 2),
            "odds_snapshot_hash": str(getattr(decision, "odds_snapshot_hash", "") or ""),
            "feature_snapshot_hash": str(getattr(decision, "feature_snapshot_hash", "") or ""),
            "model_hash": str(getattr(decision, "model_hash", "") or self._model_pkl_sha256),
            "model_version": self._model_version(),
            "calibration_hash": str(getattr(decision, "calibration_hash", "") or self._calibration_hash()),
            "bankroll_hash": self._bankroll_hash(snapshot),
            "policy_hash": str(getattr(decision, "policy_hash", "") or ""),
            "risk_limits_hash": str(getattr(decision, "risk_limits_hash", "") or ""),
        }

    def _append_pre_submit_events(self, decision: Any, bet_info: Dict[str, Any]) -> None:
        race_id = str(bet_info["race_id"])
        self._append_audit_event(
            "OddsSnapshotReceived",
            race_id,
            {
                "odds_snapshot_hash": bet_info.get("odds_snapshot_hash", ""),
                "odds": bet_info.get("odds"),
                "odds_snapshot_ts": bet_info.get("odds_snapshot_ts", ""),
                "selection": bet_info.get("selection"),
                "bet_type": bet_info.get("bet_type", "win"),
                "legs": legs_to_json(bet_info.get("legs", [])),
                "degradation_mode": bet_info.get("degradation_mode", "NORMAL"),
                "degradation_reasons": encode_reasons(bet_info.get("degradation_reasons", [])),
            },
        )
        self._append_audit_event(
            "FeatureSnapshotBuilt",
            race_id,
            {
                "feature_snapshot_hash": bet_info.get("feature_snapshot_hash", ""),
                "selection": bet_info.get("selection"),
                "bet_type": bet_info.get("bet_type", "win"),
                "legs": legs_to_json(bet_info.get("legs", [])),
                "degradation_mode": bet_info.get("degradation_mode", "NORMAL"),
                "degradation_reasons": encode_reasons(bet_info.get("degradation_reasons", [])),
            },
        )
        self._append_audit_event(
            "PredictionMade",
            race_id,
            {
                "model_hash": bet_info.get("model_hash", ""),
                "probability": bet_info.get("probability"),
                "calibrated_probability": bet_info.get("calibrated_probability"),
                "expected_value": bet_info.get("expected_value"),
                "edge": bet_info.get("edge"),
                "selection": bet_info.get("selection"),
                "bet_type": bet_info.get("bet_type", "win"),
                "legs": legs_to_json(bet_info.get("legs", [])),
                "degradation_mode": bet_info.get("degradation_mode", "NORMAL"),
                "degradation_reasons": encode_reasons(bet_info.get("degradation_reasons", [])),
            },
        )

    def execute_bet(self, decision):
        """Execute one bet request and persist the audit row.

        On SAFE_MODE, the stake is forced to the minimum lot and sent through the
        same vote dispatch pipeline.
        """

        emergency_reason = self._poll_external_emergency()
        if emergency_reason:
            return self.emergency_shutdown(
                reason=emergency_reason,
                source="external_signal",
                pause_only=True,
            )

        with self._state_lock:
            if self.circuit_breaker is not None and self.circuit_breaker.is_open():
                reason = self.circuit_breaker.reason or "CIRCUIT_OPEN"
                logger.warning("Bet execution blocked by shared circuit breaker: %s", reason)
                return {
                    "blocked": True,
                    "reason": reason,
                    "state": "STANDBY",
                }
            if self._state.emergency or self._state.standby:
                reason = self._state.reason or "EMERGENCY_BLOCKED"
                logger.warning("Bet execution blocked: %s", reason)
                return {
                    "blocked": True,
                    "reason": reason,
                    "state": "STANDBY" if self._state.standby else "SHUTDOWN",
                }

        snapshot = self._current_risk_snapshot()
        try:
            bet_info = self._build_bet_info(decision, snapshot)
        except ValueError as exc:
            race_id = str(getattr(decision, "race_id", "unknown"))
            self._append_audit_event(
                "BetTypeExecutionRejected",
                race_id,
                {
                    "race_id": race_id,
                    "selection": str(getattr(decision, "selection", "")),
                    "bet_type": str(getattr(decision, "bet_type", "")),
                    "execution_status": "BLOCKED",
                    "shadow_mode": bool(self._state.shadow_mode),
                    "safe_mode": bool(self._state.safe_mode),
                    "reason": "production_execution_unknown_bet_type",
                    "error": str(exc),
                },
            )
            return {
                "blocked": True,
                "reason": "production_execution_unknown_bet_type",
                "state": "NO_BET",
            }
        # Keep settlement consistent with execution: SAFE_MODE clamps the
        # executed stake to the minimum lot, so the decision must settle with
        # that same stake, not the pre-clamp proposal.
        executed_stake = int(bet_info.get("stake") or 0)
        if executed_stake != int(getattr(decision, "bet_size", 0) or 0):
            decision.bet_size = executed_stake
        bet_type_block_reason = self._execution_bet_type_block_reason(bet_info)
        if bet_type_block_reason is not None:
            self._append_audit_event(
                "BetTypeExecutionRejected",
                str(bet_info["race_id"]),
                {
                    **self._base_decision_payload(decision, bet_info),
                    "execution_status": "BLOCKED",
                    "reason": bet_type_block_reason,
                },
            )
            return {
                "blocked": True,
                "reason": bet_type_block_reason,
                "state": "NO_BET",
            }
        self._append_pre_submit_events(decision, bet_info)
        risk_result = self.risk_clamp.evaluate(
            self._decision_risk_clamp_input(decision, snapshot, bet_info)
        )
        bet_info["risk_clamp_allowed"] = risk_result.allowed
        bet_info["risk_limits_hash"] = risk_result.risk_limits_hash
        bet_info["risk_clamp_reason"] = risk_result.reason
        self._append_audit_event(
            "RiskClampEvaluated",
            str(bet_info["race_id"]),
            {
                "allowed": bool(risk_result.allowed),
                "reason": risk_result.reason,
                "risk_limits_hash": risk_result.risk_limits_hash,
                "max_stake": risk_result.max_stake,
                "risk_multiplier": risk_result.risk_multiplier,
                "stale_data": risk_result.reason in {"stale_odds", "stale_features"},
            },
        )

        if not risk_result.allowed:
            logger.warning("Bet execution blocked by RiskClamp: %s", risk_result.reason)
            return {
                "blocked": True,
                "reason": risk_result.reason,
                "state": "NO_BET",
                "risk_limits_hash": risk_result.risk_limits_hash,
            }

        api_result: Dict[str, Any]
        api_error: Optional[str] = None
        self._append_audit_event(
            "BetSubmitted",
            str(bet_info["race_id"]),
            self._base_decision_payload(decision, bet_info),
        )

        try:
            api_result = self._execute_real_vote(bet_info)
            with self._state_lock:
                self._state.timeout_failures = 0
                self._state.auth_failures = 0
        except Exception as exc:
            api_error = str(exc)
            category = self._classify_api_error(exc)
            logger.exception("Vote execution failed (%s): %s", category, exc)
            api_result = {
                "status": "error",
                "category": category,
                "error": api_error,
            }
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_failure()
            self._register_failure(category, exc)
        status = str(api_result.get("status", "")).lower()
        submitted = bool(api_result.get("submitted"))
        outcome_event = "BetRejected"
        if not self._state.shadow_mode and submitted and status not in {"error", "blocked", "rejected"}:
            outcome_event = "BetAccepted"
        self._append_audit_event(
            outcome_event,
            str(bet_info["race_id"]),
            {
                **self._base_decision_payload(decision, bet_info),
                "api_status": api_result.get("status", ""),
                "api_error": api_error or api_result.get("error", ""),
                "provider": api_result.get("provider", ""),
            },
        )

        row = {
            "timestamp": bet_info["timestamp"],
            "race_id": bet_info["race_id"],
            "selection": bet_info["selection"],
            "bet_type": bet_info.get("bet_type", "win"),
            "legs": legs_to_json(bet_info.get("legs", [])),
            "ordered": bet_info.get("ordered", False),
            "shadow_only": bet_info.get("shadow_only", False),
            "production_candidate": bet_info.get("production_candidate", True),
            "max_combinations_per_race": bet_info.get("max_combinations_per_race"),
            "max_race_exposure_share": bet_info.get("max_race_exposure_share"),
            "degradation_mode": bet_info.get("degradation_mode", "NORMAL"),
            "degradation_reasons": encode_reasons(bet_info.get("degradation_reasons", [])),
            "degradation_stake_multiplier": bet_info.get("degradation_stake_multiplier", 1.0),
            "degradation_allowed_bet_types": encode_reasons(bet_info.get("degradation_allowed_bet_types", [])),
            "degradation_force_no_bet": bet_info.get("degradation_force_no_bet", False),
            "probability": bet_info["probability"],
            "odds": bet_info["odds"],
            "predicted_odds": bet_info["predicted_odds"],
            "confirmed_odds": bet_info["confirmed_odds"],
            "slippage_pct": bet_info["slippage_pct"],
            "edge": bet_info["edge"],
            "expected_value": bet_info["expected_value"],
            "expected_value_per_unit": bet_info["expected_value_per_unit"],
            "calibrated_probability": bet_info["calibrated_probability"],
            "stake": bet_info["stake"],
            "mode": bet_info["mode"],
            "api_status": api_result.get("status", "submitted"),
            "api_error": api_error or api_result.get("error", ""),
            "hit": "",
            "payout": "",
            "profit": "",
            "bankroll": bet_info["bankroll"],
            "drawdown": bet_info["drawdown"],
            "risk_multiplier": bet_info["risk_multiplier"],
            "lose_streak": bet_info["lose_streak"],
            "win_streak": bet_info["win_streak"],
            "race_risk_used": bet_info["race_risk_used"],
            "model_version": bet_info["model_version"],
            "model_hash": bet_info["model_hash"],
            "model_pkl_sha256": bet_info["model_pkl_sha256"],
            "calibration_hash": bet_info["calibration_hash"],
            "calibration_last_refit_at": bet_info["calibration_last_refit_at"],
            "odds_snapshot_ts": bet_info["odds_snapshot_ts"],
            "risk_limits_hash": bet_info["risk_limits_hash"],
            "risk_clamp_reason": bet_info["risk_clamp_reason"],
            "shutdown_state": "STANDBY" if self.is_blocked() else "ACTIVE",
            "shutdown_reason": self._state.reason or "",
        }

        confirmed_odds = api_result.get("confirmed_odds")
        if confirmed_odds is None:
            confirmed_odds = api_result.get("executed_odds")
        if confirmed_odds is None:
            confirmed_odds = bet_info["predicted_odds"]

        try:
            confirmed_odds = float(confirmed_odds)
        except (TypeError, ValueError):
            confirmed_odds = float(bet_info["predicted_odds"])

        row["confirmed_odds"] = round(confirmed_odds, 4)
        row["slippage_pct"] = round(
            slippage_pct(float(row["predicted_odds"]), float(row["confirmed_odds"])),
            6,
        )
        fill_ev = round(
            fill_expected_value(float(row["probability"]), float(row["confirmed_odds"])),
            6,
        )
        row["expected_value_per_unit"] = fill_ev

        self._append_row(row)

        logger.info(
            "[EXECUTED] %s stake=%s mode=%s api_status=%s",
            decision.selection,
            bet_info["stake"],
            bet_info["mode"],
            row["api_status"],
        )

        return {
            "blocked": False,
            "stake": bet_info["stake"],
            "mode": bet_info["mode"],
            "api_result": api_result,
            "row": row,
        }

    def update_result(self, decision, hit, profit):
        """Append settlement event and optionally backfill the derived CSV report."""
        try:
            snapshot = self._current_risk_snapshot()
            settled = self._settlement_payload(decision, snapshot, hit, profit)
            self._append_audit_event("RaceSettled", str(decision.race_id), settled)
            self._append_audit_event(
                "BankrollUpdated",
                str(decision.race_id),
                {
                    **settled,
                    "bankroll": snapshot.get("bankroll"),
                    "drawdown": snapshot.get("drawdown"),
                },
            )
        except Exception as exc:
            logger.warning("Failed to write settlement event: %s", exc)

        if self.csv_report_path is not None:
            try:
                with open(self.csv_report_path, "r", newline="", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))

                for row in reversed(rows):
                    if (
                        row.get("race_id") == str(decision.race_id)
                        and row.get("selection") == str(decision.selection)
                        and not row.get("hit")
                        and not row.get("profit")
                    ):
                        row["hit"] = str(int(hit))
                        row["payout"] = str(
                            round(float(profit) + float(getattr(decision, "bet_size", 0.0) or 0.0), 2)
                            if bool(hit)
                            else 0.0
                        )
                        row["profit"] = str(round(float(profit), 2))
                        break

                with open(self.csv_report_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=self._csv_headers())
                    writer.writeheader()
                    for row in rows:
                        writer.writerow({key: row.get(key, "") for key in self._csv_headers()})
            except Exception as exc:
                logger.warning("Failed to backfill CSV settlement: %s", exc)

        # Call on_settle callback for compatibility
        try:
            if self.on_settle is not None:
                self.on_settle(settled)
        except Exception as exc:
            logger.warning("on_settle callback failed: %s", exc)

        return settled
