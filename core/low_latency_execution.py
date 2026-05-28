import asyncio
import time
import logging
import inspect
from typing import Dict, Any, Optional

from .audit_hash_log import ImmutableAuditLog
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
    ):
        self.predictor = predictor
        self.risk_manager = risk_manager
        self.ipat_client = ipat_client
        self.audit_log = audit_log
        self.circuit_breaker = circuit_breaker
        self.is_locked = False
        self.staleness_threshold = staleness_threshold

    def _predict_raw_safe(self, features: Any, odds: Any):
        predict_raw = self.predictor.predict_raw
        try:
            parameter_count = len(inspect.signature(predict_raw).parameters)
        except Exception:
            parameter_count = 2
        if parameter_count >= 2:
            return predict_raw(features, odds)
        return predict_raw(features)

    async def execute_critical_path(self, race_id: str, timeout_sec: float = 2.0):
        """
        レース締切直前に駆動する唯一のクリティカルパス。
        一切のブロッキングI/O、重いPandas操作、因果推論を禁止する。
        """
        start_time = time.perf_counter()
        # Check circuit breaker before attempting critical work
        if self.circuit_breaker is not None and self.circuit_breaker.is_open():
            logger.warning(f"[CIRCUIT OPEN] Skipping execution for Race {race_id} due to open circuit.")
            raise RuntimeError("Circuit is open; aborting critical path")
        try:
            # 1. 非同期で最新オッズをミリ秒単位で取得 (Timeout制御)
            odds_task = self.ipat_client.fetch_live_odds_async(race_id)
            odds_snapshot = await asyncio.wait_for(odds_task, timeout=timeout_sec)

            # 2. 推論
            # 2a. 鮮度チェック（provider側のタイムスタンプが含まれる場合）
            provider_ts = None
            for key in ("provider_timestamp", "scraped_at", "timestamp", "fetched_at"):
                if key in odds_snapshot:
                    try:
                        provider_ts = float(odds_snapshot.get(key))
                        break
                    except Exception:
                        pass

            if provider_ts is not None:
                if time.time() - provider_ts > self.staleness_threshold:
                    logger.warning(f"[STALE ODDS] Odds snapshot too old for Race {race_id}: age={(time.time()-provider_ts):.2f}s")
                    # Do not bet on stale data
                    return

            features = odds_snapshot.get("precomputed_feature_vector")
            predicted_probs = None
            loop = asyncio.get_running_loop()
            # Run predictor in threadpool to avoid blocking event loop
            if hasattr(self.predictor, "predict_raw"):
                odds = odds_snapshot.get("odds")
                odds_values = odds if isinstance(odds, (list, tuple)) else None
                if isinstance(features, (list, tuple)):
                    feature_items = features
                else:
                    feature_items = [features]

                probs = []
                for idx, item in enumerate(feature_items):
                    if isinstance(item, dict):
                        feature_payload = item
                    else:
                        feature_payload = {f"feature_{idx}": item}
                    odds_for_item = (
                        odds_values[idx]
                        if odds_values is not None and idx < len(odds_values)
                        else odds_values[-1] if odds_values else odds
                    )

                    prob = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            self._predict_raw_safe,
                            feature_payload,
                            odds_for_item,
                        ),
                        timeout=timeout_sec,
                    )
                    probs.append(prob)
                predicted_probs = probs
            elif hasattr(self.predictor, "predict"):
                # predictor.predict expects (race_id, selection, features, odds)
                # If features is a list of per-selection features, call predict per-selection.
                if isinstance(features, (list, tuple)):
                    probs = []
                    for sel_idx, feat in enumerate(features):
                        try:
                            p = await asyncio.wait_for(
                                loop.run_in_executor(None, self.predictor.predict, race_id, sel_idx, feat, odds_snapshot.get("odds")),
                                timeout=timeout_sec,
                            )
                        except Exception:
                            # fallback predict may also be blocking
                            p = await asyncio.wait_for(
                                loop.run_in_executor(None, getattr(self.predictor, "fallback_predict", lambda f, o: 0.0), feat, odds_snapshot.get("odds")),
                                timeout=timeout_sec,
                            )
                        probs.append(p)
                    predicted_probs = probs
                elif isinstance(features, dict):
                    try:
                        predicted_probs = [
                            await asyncio.wait_for(
                                loop.run_in_executor(None, self.predictor.predict, race_id, None, features, odds_snapshot.get("odds")),
                                timeout=timeout_sec,
                            )
                        ]
                    except Exception:
                        predicted_probs = [
                            await asyncio.wait_for(
                                loop.run_in_executor(None, getattr(self.predictor, "fallback_predict", lambda f, o: 0.0), features, odds_snapshot.get("odds")),
                                timeout=timeout_sec,
                            )
                        ]
                else:
                    # single feature vector
                    try:
                        predicted_probs = [
                            await asyncio.wait_for(
                                loop.run_in_executor(None, self.predictor.predict, race_id, None, features, odds_snapshot.get("odds")),
                                timeout=timeout_sec,
                            )
                        ]
                    except Exception:
                        predicted_probs = [
                            await asyncio.wait_for(
                                loop.run_in_executor(None, getattr(self.predictor, "fallback_predict", lambda f, o: 0.0), features, odds_snapshot.get("odds")),
                                timeout=timeout_sec,
                            )
                        ]
            else:
                raise RuntimeError("predictor has no compatible predict method")

            # 3. リスクサイジング (インメモリの数理計算のみ。DBアクセス禁止)
            if hasattr(self.risk_manager, "calculate_sizing"):
                # Run sizing in threadpool with timeout to avoid blocking critical loop
                try:
                    bet_decision = await asyncio.wait_for(
                        loop.run_in_executor(None, self.risk_manager.calculate_sizing, predicted_probs, odds_snapshot.get("odds")),
                        timeout=timeout_sec,
                    )
                except Exception:
                    logger.exception("Risk sizing failed or timed out; using safe fallback sizing")
                    bet_decision = {"should_bet": False, "allocations": []}
            else:
                # fallback sizing: small fixed allocation if prob above threshold
                prob0 = predicted_probs[0] if isinstance(predicted_probs, (list, tuple)) else predicted_probs
                prob_val = prob0 if isinstance(prob0, (int, float)) else (prob0[0] if prob0 else 0.0)
                should = float(prob_val) > 0.15
                alloc = []
                if should and hasattr(self.risk_manager, "max_bet_size"):
                    maxsize = self.risk_manager.max_bet_size()
                    size = min(maxsize, max(1.0, maxsize * 0.01))
                    alloc = [{"horse": "UNKNOWN", "amount": size}]
                bet_decision = {"should_bet": should, "allocations": alloc}

            if not bet_decision.get("should_bet"):
                logger.info(f"[NO BET] Race: {race_id} | Execution Time: {(time.perf_counter() - start_time)*1000:.2f}ms")
                return

            # 4. 投票実行
            await asyncio.wait_for(
                self.ipat_client.place_bet_async(race_id, bet_decision.get("allocations")),
                timeout=timeout_sec,
            )

            # 5. 監査用ログの非同期永続化 (I/Oを待たずにFire-and-forgetタスク化)
            if self.audit_log is not None:
                asyncio.create_task(self.persist_audit_log(race_id, odds_snapshot, bet_decision))

            logger.info(f"[BET EXECUTED] Race: {race_id} | Latency: {(time.perf_counter() - start_time)*1000:.2f}ms")

        except asyncio.TimeoutError:
            logger.critical(f"[CRITICAL TIMEOUT] Critical path exceeded timeout limit on Race {race_id}!")
            await self.trigger_emergency_safeguard(race_id)
        except Exception as e:
            logger.error(f"[EXECUTION FAILURE] Sudden collapse in critical path: {str(e)}")
            await self.trigger_emergency_safeguard(race_id)

    async def persist_audit_log(self, race_id: str, odds: Dict, decision: Dict):
        """クリティカルパスの外側で、非同期に監査トレールをDBに永続化"""
        record = {
            "race_id": race_id,
            "odds_snapshot": odds,
            "decision": decision,
        }
        try:
            await self.audit_log.append_async(record)
        except Exception:
            logger.exception("Failed to persist audit log")

    async def trigger_emergency_safeguard(self, race_id: str):
        """サーキットブレーカー作動時のパニック停止処理"""
        self.is_locked = True
        logger.warning(f"[CIRCUIT BREAKER] Safely isolated system for race {race_id}.")
        if self.circuit_breaker is not None:
            self.circuit_breaker.record_failure()

