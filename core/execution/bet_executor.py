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
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from core.execution.odds_contract import (
    decision_probability,
    fill_expected_value,
    market_odds_at_decision,
    pre_bet_expected_value,
    slippage_pct,
)


logger = logging.getLogger(__name__)


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
    """Bet execution facade with CSV audit logging and real-vote preparation.

    - SAFE_MODE=True forces every stake to the minimum lot (100 yen).
    - Real API calls are routed through `_execute_real_vote()`.
    - Emergency shutdown can block further execution on repeated API failures
      or on external system signals.
    """

    def __init__(
        self,
        risk_manager,
        log_path: str = "logs/bets.csv",
        *,
        safe_mode: Optional[bool] = None,
        shadow_mode: Optional[bool] = None,
        api_client: Any = None,
        odds_confirmer: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
        on_settle: Optional[Callable[[Dict[str, Any]], None]] = None,
        emergency_sources: Optional[Iterable[Any]] = None,
        settings_path: Optional[str] = None,
        minimum_lot: int = 100,
        max_consecutive_timeouts: int = 3,
        max_consecutive_auth_errors: int = 2,
        api_timeout_seconds: float = 0.5,
    ):

        self.risk_manager = risk_manager
        self.log_path = Path(log_path)
        self.api_client = api_client
        self.odds_confirmer = odds_confirmer
        self.on_settle = on_settle
        self.minimum_lot = int(minimum_lot)
        self.max_consecutive_timeouts = int(max_consecutive_timeouts)
        self.max_consecutive_auth_errors = int(max_consecutive_auth_errors)
        self.api_timeout_seconds = float(api_timeout_seconds)
        self._emergency_sources = list(emergency_sources or [])
        self._state_lock = threading.RLock()
        self._settings_path = self._resolve_settings_path(settings_path)
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

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_csv()
        # append-only JSONL audit log for bets (event sourcing)
        self.jsonl_path = self.log_path.parent / "bets.jsonl"
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    def _resolve_settings_path(self, settings_path: Optional[str]) -> Path:
        if settings_path is not None:
            return Path(settings_path)
        return Path(__file__).resolve().parents[2] / "config" / "settings.yaml"

    def _csv_headers(self) -> list[str]:
        return [
            "timestamp",
            "race_id",
            "selection",
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
            "profit",
            "bankroll",
            "drawdown",
            "risk_multiplier",
            "lose_streak",
            "win_streak",
            "race_risk_used",
            "shutdown_state",
            "shutdown_reason",
        ]

    def _initialize_csv(self):
        headers = self._csv_headers()

        if not self.log_path.exists():
            with open(self.log_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(headers)
            return

        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        if not lines:
            with open(self.log_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(headers)
            return

        first_row = lines[0].split(",")
        if first_row == headers:
            return

        existing_rows = list(csv.DictReader(lines)) if len(lines) > 1 else []
        with open(self.log_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in existing_rows:
                writer.writerow({key: row.get(key, "") for key in headers})

    def register_emergency_source(self, source: Any) -> None:
        self._emergency_sources.append(source)

    def is_blocked(self) -> bool:
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

    def _execution_mode_label(self) -> str:
        if self._state.shadow_mode:
            return "SHADOW_MODE"
        if self._state.safe_mode:
            return "SAFE_MODE"
        return "LIVE_MODE"

    def _build_bet_info(self, decision, snapshot: Dict[str, Any]) -> Dict[str, Any]:
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
        }

    def _execute_real_vote(self, bet_info: Dict[str, Any]) -> Dict[str, Any]:
        """Placeholder for JRA IPAT / live-vote API integration.

        If no client is configured, this falls back to a dry-run response so the
        current CSV-only workflow stays intact until a concrete API adapter is
        supplied.
        """

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
        if status_code in {401, 403}:
            return "auth"
        if "auth" in error_name or "unauthorized" in message or "forbidden" in message:
            return "auth"
        if "connection" in error_name or "network" in message:
            return "network"
        return "unexpected"

    def _register_failure(self, category: str, error: BaseException) -> Optional[Dict[str, Any]]:
        with self._state_lock:
            if category == "timeout":
                self._state.timeout_failures += 1
            elif category == "auth":
                self._state.auth_failures += 1
            else:
                self._state.timeout_failures = 0
                self._state.auth_failures = 0

            timeout_hit = self._state.timeout_failures >= self.max_consecutive_timeouts
            auth_hit = self._state.auth_failures >= self.max_consecutive_auth_errors

        if timeout_hit:
            return self.emergency_shutdown(
                reason="CONSECUTIVE_TIMEOUTS",
                source="api",
                error=error,
                pause_only=True,
            )

        if auth_hit:
            return self.emergency_shutdown(
                reason="CONSECUTIVE_AUTH_ERRORS",
                source="api",
                error=error,
                pause_only=True,
            )

        return None

    def _append_row(self, row: Dict[str, Any]):
        # Legacy CSV append for compatibility
        try:
            with open(self.log_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._csv_headers())
                writer.writerow({key: row.get(key, "") for key in self._csv_headers()})
        except Exception as exc:
            logger.warning("Failed to append CSV audit row: %s", exc)

        # Append event to JSONL audit log with hash chaining
        try:
            self._append_jsonl_event("bet_executed", row)
        except Exception as exc:
            logger.warning("Failed to append JSONL audit event: %s", exc)

    def _load_last_jsonl_hash(self) -> Optional[str]:
        if not self.jsonl_path.exists():
            return None
        try:
            with open(self.jsonl_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() == 0:
                    return None
                # read backwards for last non-empty line
                offset = 1
                while True:
                    try:
                        f.seek(-offset, os.SEEK_END)
                    except Exception:
                        f.seek(0)
                        break
                    chunk = f.read().decode("utf-8", errors="ignore")
                    if "\n" in chunk:
                        last_line = chunk.splitlines()[-1]
                        if last_line.strip():
                            try:
                                obj = json.loads(last_line)
                                return obj.get("entry_hash")
                            except Exception:
                                return None
                    offset = min(offset * 2, f.tell() + 1)
                # fallback: full read
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
        previous_hash = self._load_last_jsonl_hash()
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
            if self._state.emergency or self._state.standby:
                reason = self._state.reason or "EMERGENCY_BLOCKED"
                logger.warning("Bet execution blocked: %s", reason)
                return {
                    "blocked": True,
                    "reason": reason,
                    "state": "STANDBY" if self._state.standby else "SHUTDOWN",
                }

        snapshot = self._current_risk_snapshot()
        bet_info = self._build_bet_info(decision, snapshot)

        api_result: Dict[str, Any]
        api_error: Optional[str] = None

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
            self._register_failure(category, exc)

        row = {
            "timestamp": bet_info["timestamp"],
            "race_id": bet_info["race_id"],
            "selection": bet_info["selection"],
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
            "profit": "",
            "bankroll": bet_info["bankroll"],
            "drawdown": bet_info["drawdown"],
            "risk_multiplier": bet_info["risk_multiplier"],
            "lose_streak": bet_info["lose_streak"],
            "win_streak": bet_info["win_streak"],
            "race_risk_used": bet_info["race_risk_used"],
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
        """Backfill hit/profit into the existing CSV audit row."""
        # New behavior: append a settlement event to JSONL (append-only).
        settled = {
            "race_id": decision.race_id,
            "selection": decision.selection,
            "hit": int(hit),
            "profit": round(float(profit), 2),
        }
        try:
            self._append_jsonl_event("bet_settled", settled)
        except Exception as exc:
            logger.warning("Failed to write settlement event: %s", exc)

        # Call on_settle callback for compatibility
        try:
            if self.on_settle is not None:
                self.on_settle(settled)
        except Exception as exc:
            logger.warning("on_settle callback failed: %s", exc)

        return settled