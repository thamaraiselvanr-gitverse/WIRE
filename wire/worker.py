"""Reconstruction worker: drains the durable job queue.

Run one or more of these alongside the API::

    python -m wire.worker

Each worker polls the ``reconstruction_jobs`` table, atomically claims a pending
job, runs the reconstruction pipeline, and records the outcome (retrying on
failure). Because claiming is a guarded UPDATE, multiple workers can run
concurrently against the same database without a message broker.
"""

import asyncio
from typing import Awaitable, Callable, Optional, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from wire.api import job_queue
from wire.utils.errors import ComplianceError

logger = structlog.get_logger(__name__)

# A runner takes a URL and the project-scoped run id, returning a fidelity
# score. Injectable for testing.
Runner = Callable[[str, str], Awaitable[float]]
# Produces a new AsyncSession (e.g. sessionmaker); used as an async context mgr.
SessionFactory = Callable[[], AsyncSession]


async def _default_runner(url: str, run_id: str) -> float:
    from wire.orchestrator.execution_router import ExecutionRouter

    return await ExecutionRouter().execute_pipeline(url, run_id=run_id)


async def process_one(session_factory: SessionFactory, runner: Runner) -> bool:
    """Claim and run a single job. Returns True if one was processed.

    The pipeline runs outside the claim transaction so a long reconstruction
    never holds a DB lock; the result is written back in a fresh session.
    Output is namespaced per project (``project_<id>``) so concurrent users
    reconstructing the same domain never share a run directory.
    """
    async with session_factory() as db:
        job = await job_queue.claim_next(db)
        if job is None:
            return False
        job_id, url = cast(int, job.id), cast(str, job.url)
        run_id = f"project_{cast(int, job.project_id)}"

    try:
        fidelity = await runner(url, run_id)
    except ComplianceError as e:
        # Legal/policy block (e.g. robots.txt) — never retry.
        logger.warning("job_blocked_compliance", job_id=job_id, error=str(e))
        async with session_factory() as db:
            await job_queue.fail_permanent(db, job_id, str(e))
        return True
    except Exception as e:
        logger.error("job_run_failed", job_id=job_id, error=str(e))
        async with session_factory() as db:
            await job_queue.fail(db, job_id, str(e))
        return True

    async with session_factory() as db:
        await job_queue.complete(db, job_id, fidelity)
    return True


async def run_worker(
    session_factory: SessionFactory,
    runner: Optional[Runner] = None,
    poll_interval: float = 2.0,
    stale_seconds: float = 1800,
    max_iterations: Optional[int] = None,
) -> None:
    """Continuously recover stale jobs and drain the queue.

    ``max_iterations`` bounds the loop (used by tests); ``None`` runs forever.
    """
    runner = runner or _default_runner
    logger.info("worker_started", poll_interval=poll_interval)
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        async with session_factory() as db:
            await job_queue.recover_stale(db, stale_seconds)
        processed = await process_one(session_factory, runner)
        if not processed:
            await asyncio.sleep(poll_interval)


def main() -> None:  # pragma: no cover - process entry point
    from wire.api.database import AsyncSessionLocal

    asyncio.run(run_worker(AsyncSessionLocal))


if __name__ == "__main__":  # pragma: no cover
    main()
