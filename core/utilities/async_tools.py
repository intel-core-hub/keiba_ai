# core/utilities/async_tools.py

import contextvars
import inspect
import threading
import time
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass, field
from functools import wraps
from typing import Callable, Any, Optional, Dict, List
from concurrent.futures import ThreadPoolExecutor, Future
import logging

logger = logging.getLogger(__name__)


@dataclass
class PhaseTiming:
    name: str
    start_ns: int
    end_ns: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ns(self) -> int:
        if self.end_ns <= self.start_ns:
            return 0
        return self.end_ns - self.start_ns

    @property
    def duration_ms(self) -> float:
        return self.duration_ns / 1_000_000.0


@dataclass
class LatencyTraceReport:
    name: str
    started_ns: int
    ended_ns: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    phases: List[PhaseTiming] = field(default_factory=list)
    total_threshold_ms: float = 3000.0
    default_phase_threshold_ms: float = 1000.0
    phase_thresholds_ms: Dict[str, float] = field(default_factory=dict)

    @property
    def total_duration_ns(self) -> int:
        if self.ended_ns <= self.started_ns:
            return 0
        return self.ended_ns - self.started_ns

    @property
    def total_duration_ms(self) -> float:
        return self.total_duration_ns / 1_000_000.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "metadata": dict(self.metadata),
            "started_ns": self.started_ns,
            "ended_ns": self.ended_ns,
            "total_duration_ms": self.total_duration_ms,
            "total_threshold_ms": self.total_threshold_ms,
            "default_phase_threshold_ms": self.default_phase_threshold_ms,
            "phase_thresholds_ms": dict(self.phase_thresholds_ms),
            "phases": [
                {
                    "name": phase.name,
                    "start_ns": phase.start_ns,
                    "end_ns": phase.end_ns,
                    "duration_ns": phase.duration_ns,
                    "duration_ms": phase.duration_ms,
                    "metadata": dict(phase.metadata),
                }
                for phase in self.phases
            ],
        }


@dataclass
class _LatencyTraceState:
    report: LatencyTraceReport
    token: Optional[contextvars.Token] = None


class _LatencyPhaseContext(AbstractContextManager, AbstractAsyncContextManager):
    def __init__(
        self,
        profiler: "LatencyProfiler",
        phase_name: str,
        threshold_ms: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.profiler = profiler
        self.phase_name = phase_name
        self.threshold_ms = threshold_ms
        self.metadata = metadata or {}
        self._state: Optional[_LatencyTraceState] = None
        self._created_trace = False
        self._phase: Optional[PhaseTiming] = None

    def __enter__(self):
        self._state, self._created_trace = self.profiler._ensure_trace_state()
        self._phase = PhaseTiming(
            name=self.phase_name,
            start_ns=time.perf_counter_ns(),
            metadata=dict(self.metadata),
        )
        return self

    def __exit__(self, exc_type, exc, tb):
        self.profiler._finish_phase(
            state=self._state,
            phase=self._phase,
            threshold_ms=self.threshold_ms,
        )
        if self._created_trace:
            self.profiler._finalize_trace(self._state)
        return False

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb):
        return self.__exit__(exc_type, exc, tb)


class _LatencyTraceContext(AbstractContextManager, AbstractAsyncContextManager):
    def __init__(
        self,
        profiler: "LatencyProfiler",
        trace_name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.profiler = profiler
        self.trace_name = trace_name
        self.metadata = metadata or {}
        self._state: Optional[_LatencyTraceState] = None

    def __enter__(self):
        self._state = self.profiler._start_trace(
            self.trace_name,
            self.metadata,
        )
        return self._state.report

    def __exit__(self, exc_type, exc, tb):
        self.profiler._finalize_trace(self._state)
        return False

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb):
        return self.__exit__(exc_type, exc, tb)


class LatencyProfiler:
    """High precision profiler for pre-bet critical paths.

    Example:
        profiler = LatencyProfiler(total_threshold_ms=3000, default_phase_threshold_ms=1000)

        async with profiler.trace("shadow_trade", {"race_id": race_id}) as report:
            async with profiler.phase("Data Acquisition"):
                odds = await fetch_odds()
            with profiler.phase("Inference"):
                score = model.predict(features)
            with profiler.phase("Risk Calculation"):
                size = risk_manager.size_bet(score)
            with profiler.phase("Execution"):
                await place_bet(size)
    """

    def __init__(
        self,
        *,
        total_threshold_ms: float = 3000.0,
        default_phase_threshold_ms: float = 1000.0,
        phase_thresholds_ms: Optional[Dict[str, float]] = None,
        logger_obj: Optional[logging.Logger] = None,
        alert_level: int = logging.CRITICAL,
        history_limit: int = 100,
    ):
        self.total_threshold_ms = float(total_threshold_ms)
        self.default_phase_threshold_ms = float(default_phase_threshold_ms)
        self.phase_thresholds_ms = dict(phase_thresholds_ms or {})
        self.logger = logger_obj or logger
        self.alert_level = alert_level
        self.history_limit = max(1, int(history_limit))
        self._current_trace: contextvars.ContextVar[Optional[_LatencyTraceState]] = contextvars.ContextVar(
            "latency_profiler_trace",
            default=None,
        )
        self._history: List[LatencyTraceReport] = []

    def trace(
        self,
        trace_name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> _LatencyTraceContext:
        return _LatencyTraceContext(self, trace_name, metadata)

    def phase(
        self,
        phase_name: str,
        *,
        threshold_ms: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> _LatencyPhaseContext:
        return _LatencyPhaseContext(self, phase_name, threshold_ms, metadata)

    def profile(
        self,
        phase_name: Optional[str] = None,
        *,
        threshold_ms: Optional[float] = None,
    ):
        """Decorator for timing a whole sync or async callable as one phase."""

        def decorator(func: Callable):
            resolved_name = phase_name or getattr(func, "__name__", "operation")

            if inspect.iscoroutinefunction(func):

                @wraps(func)
                async def async_wrapper(*args, **kwargs):
                    async with self.phase(resolved_name, threshold_ms=threshold_ms):
                        return await func(*args, **kwargs)

                return async_wrapper

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                with self.phase(resolved_name, threshold_ms=threshold_ms):
                    return func(*args, **kwargs)

            return sync_wrapper

        return decorator

    def last_report(self) -> Optional[LatencyTraceReport]:
        if not self._history:
            return None
        return self._history[-1]

    def history(self) -> List[LatencyTraceReport]:
        return list(self._history)

    def _start_trace(
        self,
        trace_name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> _LatencyTraceState:
        report = LatencyTraceReport(
            name=trace_name,
            started_ns=time.perf_counter_ns(),
            metadata=dict(metadata or {}),
            total_threshold_ms=self.total_threshold_ms,
            default_phase_threshold_ms=self.default_phase_threshold_ms,
            phase_thresholds_ms=dict(self.phase_thresholds_ms),
        )
        state = _LatencyTraceState(report=report)
        state.token = self._current_trace.set(state)
        return state

    def _ensure_trace_state(self) -> tuple[_LatencyTraceState, bool]:
        state = self._current_trace.get()
        if state is not None:
            return state, False
        state = self._start_trace("standalone_latency_trace")
        return state, True

    def _finish_phase(
        self,
        state: Optional[_LatencyTraceState],
        phase: Optional[PhaseTiming],
        threshold_ms: Optional[float] = None,
    ) -> None:
        if state is None or phase is None:
            return

        phase.end_ns = time.perf_counter_ns()
        state.report.phases.append(phase)

        effective_threshold_ms = self.phase_thresholds_ms.get(
            phase.name,
            self.default_phase_threshold_ms,
        )
        if threshold_ms is not None:
            effective_threshold_ms = float(threshold_ms)

        duration_ms = phase.duration_ms
        if duration_ms > effective_threshold_ms:
            self.logger.log(
                self.alert_level,
                (
                    "Latency phase threshold exceeded | trace=%s phase=%s "
                    "duration_ms=%.3f threshold_ms=%.3f metadata=%s"
                ),
                state.report.name,
                phase.name,
                duration_ms,
                effective_threshold_ms,
                phase.metadata,
            )

    def _finalize_trace(self, state: Optional[_LatencyTraceState]) -> Optional[LatencyTraceReport]:
        if state is None:
            return None

        state.report.ended_ns = time.perf_counter_ns()
        total_ms = state.report.total_duration_ms

        if total_ms > state.report.total_threshold_ms:
            self.logger.log(
                self.alert_level,
                (
                    "Latency total threshold exceeded | trace=%s total_ms=%.3f "
                    "threshold_ms=%.3f phases=%d metadata=%s"
                ),
                state.report.name,
                total_ms,
                state.report.total_threshold_ms,
                len(state.report.phases),
                state.report.metadata,
            )

        token = state.token
        if token is not None:
            self._current_trace.reset(token)

        self._history.append(state.report)
        if len(self._history) > self.history_limit:
            self._history = self._history[-self.history_limit :]

        return state.report

    def summarize_latest(self) -> Optional[Dict[str, Any]]:
        report = self.last_report()
        if report is None:
            return None
        return report.to_dict()


@dataclass
class CachedResult:
    value: Any = None
    updated_at: float = 0.0
    in_flight: bool = False
    error: Optional[str] = None
    future: Optional[Future] = None


class LatestResultCache:
    """Store and refresh the latest successful result without blocking readers.

    `latest_or_schedule()` returns the most recent cached value immediately and,
    if the entry is stale or missing, submits a refresh in the background.
    """

    def __init__(self, max_workers: int = 2, ttl_seconds: float = 15.0):
        self.pool = ThreadPoolManager(max_workers=max_workers)
        self.ttl_seconds = float(ttl_seconds)
        self._lock = threading.Lock()
        self._cache: Dict[str, CachedResult] = {}

    def latest(self, key: str, default: Any = None) -> Any:
        with self._lock:
            record = self._cache.get(key)
            if record is None or record.value is None:
                return default
            return record.value

    def status(self, key: str) -> Dict[str, Any]:
        with self._lock:
            record = self._cache.get(key, CachedResult())
            age = time.time() - record.updated_at if record.updated_at else None
            return {
                "has_value": record.value is not None,
                "updated_at": record.updated_at,
                "age_seconds": age,
                "in_flight": record.in_flight,
                "error": record.error,
            }

    def put(self, key: str, value: Any) -> Any:
        with self._lock:
            self._cache[key] = CachedResult(
                value=value,
                updated_at=time.time(),
                in_flight=False,
                error=None,
                future=None,
            )
        return value

    def _refresh_needed(self, key: str) -> bool:
        record = self._cache.get(key)
        if record is None or record.value is None:
            return True
        if record.in_flight:
            return False
        return (time.time() - record.updated_at) >= self.ttl_seconds

    def schedule(self, key: str, producer: Callable[..., Any], *args, **kwargs) -> Any:
        """Return current cached value and schedule a refresh if needed."""
        with self._lock:
            record = self._cache.get(key)
            cached_value = record.value if record is not None else None
            if record is None:
                record = CachedResult()
                self._cache[key] = record

            if record.in_flight or not self._refresh_needed(key):
                return cached_value

            record.in_flight = True
            record.error = None

        future = self.pool.submit(producer, *args, **kwargs)

        def _done_callback(done_future: Future):
            try:
                value = done_future.result()
                error = None
            except Exception as exc:  # pragma: no cover - background diagnostics
                value = None
                error = str(exc)
                logger.exception("LatestResultCache refresh error for %s", key)

            with self._lock:
                current = self._cache.get(key, CachedResult())
                if value is not None:
                    current.value = value
                    current.updated_at = time.time()
                    current.error = None
                else:
                    current.error = error
                current.in_flight = False
                current.future = None
                self._cache[key] = current

        with self._lock:
            record.future = future

        future.add_done_callback(_done_callback)
        return cached_value

    def latest_or_schedule(self, key: str, producer: Callable[..., Any], *args, default: Any = None, **kwargs) -> Any:
        value = self.schedule(key, producer, *args, **kwargs)
        if value is None:
            return default
        return value

    def shutdown(self, wait: bool = True):
        self.pool.shutdown(wait=wait)


class BackgroundTask:
    """
    バックグラウンドで実行するタスク
    
    使用例:
        task = BackgroundTask(my_function, arg1, arg2, key=value)
        task.start()
        task.join()  # 完了を待つ
    """

    def __init__(self, func: Callable, *args, **kwargs):
        """
        初期化
        
        Args:
            func: 実行する関数
            *args: 位置引数
            **kwargs: キーワード引数
        """
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.thread = None
        self.result = None
        self.exception = None

    def start(self):
        """タスクを開始"""
        self.thread = threading.Thread(
            target=self._run,
            daemon=False
        )
        self.thread.start()

    def _run(self):
        """スレッド内で実行"""
        try:
            self.result = self.func(*self.args, **self.kwargs)
        except Exception as e:
            self.exception = e
            logger.error(f"BackgroundTask error: {e}")

    def join(self, timeout: Optional[float] = None) -> bool:
        """
        タスクの完了を待つ
        
        Args:
            timeout: タイムアウト秒数（Noneは無限待機）
            
        Returns:
            True: 完了, False: タイムアウト
        """
        if self.thread is None:
            return True
        self.thread.join(timeout=timeout)
        return not self.thread.is_alive()

    def is_alive(self) -> bool:
        """実行中かどうか"""
        return self.thread is not None and self.thread.is_alive()

    def get_result(self) -> Any:
        """結果を取得（エラーがあれば例外を発生）"""
        if self.exception is not None:
            raise self.exception
        return self.result


class ThreadPoolManager:
    """
    スレッドプール管理
    
    使用例:
        manager = ThreadPoolManager(max_workers=4)
        future = manager.submit(my_function, arg1, arg2)
        result = future.result(timeout=10)
    """

    def __init__(self, max_workers: int = 4):
        """
        初期化
        
        Args:
            max_workers: 最大スレッド数
        """
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.futures = []

    def submit(self, func: Callable, *args, **kwargs) -> Future:
        """
        タスクを投入
        
        Args:
            func: 実行する関数
            *args: 位置引数
            **kwargs: キーワード引数
            
        Returns:
            Future オブジェクト
        """
        future = self.executor.submit(func, *args, **kwargs)
        self.futures.append(future)
        return future

    def submit_task(self, task: BackgroundTask):
        """
        BackgroundTask を投入
        
        Args:
            task: BackgroundTask インスタンス
        """
        task.start()
        self.futures.append(task.thread)

    def shutdown(self, wait: bool = True):
        """
        スレッドプールをシャットダウン
        
        Args:
            wait: 完了を待つかどうか
        """
        self.executor.shutdown(wait=wait)

    def wait_all(self, timeout: Optional[float] = None) -> bool:
        """
        すべてのタスクの完了を待つ
        
        Args:
            timeout: タイムアウト秒数
            
        Returns:
            True: すべて完了, False: タイムアウト
        """
        try:
            for future in self.futures:
                future.result(timeout=timeout)
            return True
        except TimeoutError:
            return False


def run_in_thread(func: Callable, *args, **kwargs) -> BackgroundTask:
    """
    関数をスレッドで実行する簡易関数
    
    Args:
        func: 実行する関数
        *args: 位置引数
        **kwargs: キーワード引数
        
    Returns:
        BackgroundTask インスタンス
    """
    task = BackgroundTask(func, *args, **kwargs)
    task.start()
    return task


def run_periodically(
    func: Callable,
    interval: float,
    *args,
    **kwargs
) -> BackgroundTask:
    """
    定期的に関数を実行する
    
    Args:
        func: 実行する関数
        interval: 実行間隔（秒）
        *args: 位置引数
        **kwargs: キーワード引数
        
    Returns:
        BackgroundTask インスタンス（stop_event で停止可能）
    """
    stop_event = threading.Event()

    def periodic_wrapper():
        while not stop_event.is_set():
            try:
                func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Periodic task error: {e}")
            time.sleep(interval)

    task = BackgroundTask(periodic_wrapper)
    task.stop_event = stop_event
    task.start()
    return task


def threadsafe_call(func: Callable, *args, **kwargs) -> Any:
    """
    スレッドセーフに関数を呼び出す
    
    Args:
        func: 実行する関数
        *args: 位置引数
        **kwargs: キーワード引数
        
    Returns:
        関数の戻り値
    """
    task = BackgroundTask(func, *args, **kwargs)
    task.start()
    task.join()
    return task.get_result()
