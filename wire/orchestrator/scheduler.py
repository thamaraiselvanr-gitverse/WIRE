"""Bounded-concurrency task scheduling for a single node.

The previous version advertised "NUMA-aware" scheduling but ran everything
serially with a counter. This does the honest, useful thing instead: cap how
many coroutines run at once with an ``asyncio.Semaphore`` so a multi-page crawl
fans out without opening dozens of browser pages simultaneously. It also tracks
peak concurrency so callers can see the limit is actually being applied.
"""

import asyncio
from typing import Awaitable, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")

_DEFAULT_CONCURRENCY = 4


class TaskScheduler:
    """Runs awaitables with a hard ceiling on simultaneous execution."""

    def __init__(self, max_concurrency: int = _DEFAULT_CONCURRENCY) -> None:
        self.max_concurrency = max(1, max_concurrency)
        self._sem = asyncio.Semaphore(self.max_concurrency)
        self.active_tasks = 0
        self.peak_concurrency = 0

    async def schedule(self, coro: Awaitable[T]) -> T:
        """Await ``coro`` under the concurrency limit."""
        async with self._sem:
            self.active_tasks += 1
            self.peak_concurrency = max(self.peak_concurrency, self.active_tasks)
            logger.debug("scheduling_task", active=self.active_tasks)
            try:
                return await coro
            finally:
                self.active_tasks -= 1

    async def run_all(self, coros: list[Awaitable[T]]) -> list[T]:
        """Run many awaitables with bounded parallelism, preserving input order.

        Results come back in the same order as ``coros`` regardless of which
        finished first — the caller can zip them straight back to their inputs.
        """
        if not coros:
            return []
        logger.info(
            "running_batch",
            count=len(coros),
            max_concurrency=self.max_concurrency,
        )
        return await asyncio.gather(*(self.schedule(c) for c in coros))
