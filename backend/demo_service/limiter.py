from math import ceil
from threading import Lock
from time import monotonic


class FixedWindowLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock=monotonic,
    ):
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock

        self.started_at = clock()
        self.count = 0
        self.lock = Lock()

    def acquire(self) -> int | None:
        with self.lock:
            now = self.clock()
            elapsed = now - self.started_at

            if elapsed >= self.window_seconds:
                self.started_at = now
                self.count = 0
                elapsed = 0

            if self.count >= self.limit:
                return max(
                    1,
                    ceil(self.window_seconds - elapsed),
                )

            self.count += 1
            return None