"""In-process sliding-window rate limiter.

The API runs as a single uvicorn process (see Dockerfile), so counters kept in
memory are shared by every request. They reset when the process restarts;
running more than one worker would need a shared store (e.g. the database or
Redis) instead.
"""

import hashlib
import math
import time
from collections import deque
from collections.abc import Callable
from threading import Lock

__all__ = ["RateLimitExceededError", "SlidingWindowRateLimiter"]


class RateLimitExceededError(Exception):
    """Raised when a key went over its limit; carries the seconds to wait."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class SlidingWindowRateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    @staticmethod
    def _key(raw_key: str) -> str:
        # Keys are emails: keep only a digest in memory.
        return hashlib.sha256(raw_key.casefold().encode()).hexdigest()

    def _prune(self, key: str, now: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        while hits and now - hits[0] >= self.window_seconds:
            hits.popleft()
        if not hits:
            # Dropping empty keys keeps memory bounded by active keys only.
            del self._hits[key]
            return None
        return hits

    def _retry_after(self, hits: deque[float], now: float) -> int:
        return max(1, math.ceil(self.window_seconds - (now - hits[0])))

    def check(self, raw_key: str) -> None:
        """Raise if the key is already at its limit, without counting a hit."""
        key, now = self._key(raw_key), self._clock()
        with self._lock:
            hits = self._prune(key, now)
            if hits is not None and len(hits) >= self.limit:
                raise RateLimitExceededError(self._retry_after(hits, now))

    def hit(self, raw_key: str) -> None:
        """Count one hit, raising instead when the key is at its limit."""
        key, now = self._key(raw_key), self._clock()
        with self._lock:
            hits = self._prune(key, now)
            if hits is not None and len(hits) >= self.limit:
                raise RateLimitExceededError(self._retry_after(hits, now))
            self._hits.setdefault(key, deque()).append(now)

    def reset(self, raw_key: str | None = None) -> None:
        with self._lock:
            if raw_key is None:
                self._hits.clear()
            else:
                self._hits.pop(self._key(raw_key), None)
