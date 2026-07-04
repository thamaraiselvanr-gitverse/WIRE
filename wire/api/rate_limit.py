"""Lightweight in-process rate limiting.

Reconstruction launches a real browser per request, so an unbounded endpoint is
trivially abused; auth endpoints need brute-force protection. This is a simple
per-key sliding-window limiter held in memory — correct for a single process.
A multi-process / multi-node deployment should back this with Redis instead;
the interface (``check``) stays the same.
"""

import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import HTTPException, status


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max(1, max_requests)
        self.window_seconds = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Record a hit for ``key``; raise 429 if it exceeds the window budget."""
        now = time.monotonic()
        bucket = self._hits[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            retry = max(1, int(bucket[0] + self.window_seconds - now))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please slow down and retry shortly.",
                headers={"Retry-After": str(retry)},
            )
        bucket.append(now)

    def reset(self) -> None:
        """Clear all recorded hits (used between tests)."""
        self._hits.clear()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Reconstruction is expensive (a browser per call): cap per authenticated user.
reconstruction_limiter = RateLimiter(
    max_requests=_int_env("WIRE_RATE_LIMIT_RECONSTRUCTIONS", 10),
    window_seconds=60.0,
)

# Auth endpoints: cap per client IP to blunt credential stuffing / brute force.
auth_limiter = RateLimiter(
    max_requests=_int_env("WIRE_RATE_LIMIT_AUTH", 20),
    window_seconds=60.0,
)
