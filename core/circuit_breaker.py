import time
import threading
from dataclasses import dataclass, field


@dataclass
class SharedCircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: float = 60.0  # seconds before attempting half-open

    failures: int = 0
    last_failure_time: float = 0.0
    open_since: float | None = None
    reason: str | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def record_success(self):
        with self._lock:
            self.failures = 0
            self.open_since = None
            self.reason = None

    def record_failure(self):
        with self._lock:
            self.failures += 1
            self.last_failure_time = time.time()
            if self.failures >= self.failure_threshold:
                self.force_open("FAILURE_THRESHOLD")

    def force_open(self, reason: str):
        with self._lock:
            self.open_since = time.time()
            self.reason = reason

    def is_open(self) -> bool:
        with self._lock:
            if self.open_since is None:
                return False
            # still open until recovery_timeout elapsed
            if (time.time() - self.open_since) < self.recovery_timeout:
                return True
            # allow half-open attempt
            return False

    def status(self):
        with self._lock:
            return {
                "open": self.is_open(),
                "failures": self.failures,
                "reason": self.reason,
                "open_since": self.open_since,
                "last_failure_time": self.last_failure_time,
            }


CircuitBreaker = SharedCircuitBreaker
