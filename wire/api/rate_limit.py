"""Rate limiting: Redis-backed when ``WIRE_REDIS_URL`` is set, in-process
otherwise.

Reconstruction launches a real browser per request, so an unbounded endpoint is
trivially abused; auth endpoints need brute-force protection. The in-memory
limiter is correct for a single API process. A multi-process / multi-node
deployment MUST set ``WIRE_REDIS_URL`` so all replicas share one budget —
otherwise each process silently enforces its own copy of the limit. Both
implementations expose the same interface (``check``/``reset``).
"""

import os
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional, Union

import structlog
from fastapi import HTTPException, status

logger = structlog.get_logger(__name__)


def _raise_429(retry_seconds: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded. Please slow down and retry shortly.",
        headers={"Retry-After": str(max(1, retry_seconds))},
    )


class RateLimiter:
    """Per-key sliding-window limiter held in process memory."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max(1, max_requests)
        self.window_seconds = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._last_prune = time.monotonic()

    def check(self, key: str) -> None:
        """Record a hit for ``key``; raise 429 if it exceeds the window budget."""
        now = time.monotonic()
        self._prune(now)
        bucket = self._hits[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            _raise_429(int(bucket[0] + self.window_seconds - now))
        bucket.append(now)

    def _prune(self, now: float) -> None:
        """Periodically drop idle keys so memory doesn't grow with user count."""
        if now - self._last_prune < self.window_seconds:
            return
        self._last_prune = now
        cutoff = now - self.window_seconds
        for key in [k for k, b in self._hits.items() if not b or b[-1] <= cutoff]:
            del self._hits[key]

    def reset(self) -> None:
        """Clear all recorded hits (used between tests)."""
        self._hits.clear()


class RedisRateLimiter:
    """Fixed-window limiter on Redis: one shared budget across all replicas.

    Uses ``INCR`` + ``EXPIRE`` per (key, window) bucket — simple, atomic
    enough for abuse control, and free of per-request round-trip storms.
    If Redis is unreachable the limiter FAILS OPEN (allows the request) and
    logs a warning: rate limiting is an abuse control, not an auth boundary,
    and taking the product down when Redis blips is the worse failure.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        client: Optional[Any] = None,
        name: str = "default",
    ) -> None:
        self.max_requests = max(1, max_requests)
        self.window_seconds = max(1.0, window_seconds)
        self.name = name
        self._client = client

    def _redis(self) -> Any:
        if self._client is None:
            import redis

            self._client = redis.Redis.from_url(
                os.environ["WIRE_REDIS_URL"], socket_timeout=1.0
            )
        return self._client

    def check(self, key: str) -> None:
        window = int(self.window_seconds)
        bucket = int(time.time()) // window
        redis_key = f"wire:rl:{self.name}:{key}:{bucket}"
        try:
            client = self._redis()
            count = client.incr(redis_key)
            if count == 1:
                client.expire(redis_key, window)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("rate_limit_redis_unavailable", error=str(e))
            return  # fail open: availability over strictness for abuse control
        if int(count) > self.max_requests:
            _raise_429(window - (int(time.time()) % window))

    def reset(self) -> None:  # pragma: no cover - test/ops convenience
        """No-op: Redis buckets expire on their own."""


Limiter = Union[RateLimiter, RedisRateLimiter]


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def build_limiter(max_requests: int, window_seconds: float, name: str) -> Limiter:
    """Redis-backed when WIRE_REDIS_URL is configured, else in-process."""
    if os.environ.get("WIRE_REDIS_URL"):
        return RedisRateLimiter(max_requests, window_seconds, name=name)
    return RateLimiter(max_requests, window_seconds)


# Reconstruction is expensive (a browser per call): cap per authenticated user.
reconstruction_limiter: Limiter = build_limiter(
    max_requests=_int_env("WIRE_RATE_LIMIT_RECONSTRUCTIONS", 10),
    window_seconds=60.0,
    name="reconstruction",
)

# Auth endpoints: cap per client IP to blunt credential stuffing / brute force.
auth_limiter: Limiter = build_limiter(
    max_requests=_int_env("WIRE_RATE_LIMIT_AUTH", 20),
    window_seconds=60.0,
    name="auth",
)
