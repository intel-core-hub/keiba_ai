import time
from dataclasses import dataclass


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: float = 60.0  # seconds before attempting half-open

    failures: int = 0
    last_failure_time: float = 0.0
    open_since: float | None = None

    def record_success(self):
        self.failures = 0
        self.open_since = None

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.open_since = time.time()

    def is_open(self) -> bool:
        if self.open_since is None:
            return False
        # still open until recovery_timeout elapsed
        if (time.time() - self.open_since) < self.recovery_timeout:
            return True
        # allow half-open attempt
        return False
