"""In-memory sliding-window limiter for failed logins.

Counts failures per key within a time window and reports how long a blocked key must wait.
State lives in this process's memory: correct for a single backend process. Several worker
processes or servers would need a shared store (e.g. Redis) instead.
"""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class FailureLimiter:
    def __init__(self, max_failures: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self.clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()  # sync endpoints run in a thread pool

    def _prune(self, key: str, now: float) -> deque[float]:
        failures = self._failures[key]
        while failures and now - failures[0] >= self.window:
            failures.popleft()
        return failures

    def retry_after(self, key: str) -> float:
        """Seconds until `key` may try again (0 if it isn't blocked)."""
        with self._lock:
            now = self.clock()
            failures = self._prune(key, now)
            if len(failures) < self.max_failures:
                return 0.0
            return max(0.0, self.window - (now - failures[0]))

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self.clock()
            self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()


LOGIN_WINDOW_SECONDS = 15 * 60
login_failures_by_account = FailureLimiter(max_failures=5, window_seconds=LOGIN_WINDOW_SECONDS)
"""Per email + client address: stops password guessing against one account."""
login_failures_by_ip = FailureLimiter(max_failures=20, window_seconds=LOGIN_WINDOW_SECONDS)
"""Per client address: stops one source trying many accounts."""
