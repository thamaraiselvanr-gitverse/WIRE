"""Durable, DB-backed reconstruction job queue.

Persisting jobs (rather than firing ``asyncio.create_task``) makes the pipeline
resilient: work survives an API restart, is retried on failure, and can be
processed by one or more separate worker processes. Jobs are claimed with an
optimistic ``UPDATE … WHERE status='pending'`` guard, which is safe across
concurrent workers on both SQLite and PostgreSQL without a broker.

Every claim mints a ``claim_token``; result writes are guarded by it. If a
job is requeued as stale (worker presumed dead) and re-claimed elsewhere, a
still-alive original worker's late result is discarded instead of
double-writing. Running workers heartbeat so stale recovery only requeues
jobs whose worker has actually stopped responding, not long-but-alive runs.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .metrics import counter
from .models import Project, ReconstructionJob

logger = structlog.get_logger(__name__)


async def enqueue(db: AsyncSession, project_id: int, url: str) -> ReconstructionJob:
    """Persist a new pending job for ``project_id``."""
    job = ReconstructionJob(project_id=project_id, url=url, status="pending")
    db.add(job)
    await db.commit()
    await db.refresh(job)
    counter("jobs_enqueued_total").inc()
    logger.info("job_enqueued", job_id=job.id, project_id=project_id)
    return job


async def claim_next(db: AsyncSession) -> Optional[ReconstructionJob]:
    """Atomically claim the oldest pending job (pending -> running).

    Returns the claimed job (with a fresh ``claim_token``), or None if the
    queue is empty or another worker won the race for the candidate job.
    """
    result = await db.execute(
        select(ReconstructionJob)
        .where(ReconstructionJob.status == "pending")
        .order_by(ReconstructionJob.id)
        .limit(1)
    )
    job = result.scalars().first()
    if job is None:
        return None

    claim_token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    claimed = await db.execute(
        update(ReconstructionJob)
        .where(
            ReconstructionJob.id == job.id,
            ReconstructionJob.status == "pending",
        )
        .values(
            status="running",
            attempts=ReconstructionJob.attempts + 1,
            started_at=now,
            heartbeat_at=now,
            claim_token=claim_token,
        )
    )
    await db.commit()
    if claimed.rowcount == 0:  # type: ignore[attr-defined]
        return None  # lost the race to another worker
    await db.refresh(job)
    logger.info("job_claimed", job_id=job.id, attempt=job.attempts)
    return job


async def heartbeat(db: AsyncSession, job_id: int, claim_token: str) -> bool:
    """Record that this worker is still alive on its claimed job.

    Returns False if the claim no longer belongs to this worker (the job was
    requeued as stale and possibly re-claimed) — the caller should treat its
    run as orphaned.
    """
    result = await db.execute(
        update(ReconstructionJob)
        .where(
            ReconstructionJob.id == job_id,
            ReconstructionJob.claim_token == claim_token,
            ReconstructionJob.status == "running",
        )
        .values(heartbeat_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def complete(
    db: AsyncSession, job_id: int, fidelity: float, claim_token: Optional[str] = None
) -> bool:
    """Mark a job (and its project) completed.

    When ``claim_token`` is given, the write only lands if this worker still
    owns the claim; a stale worker's late result is discarded (returns False).
    """
    conditions = [ReconstructionJob.id == job_id]
    if claim_token is not None:
        conditions.append(ReconstructionJob.claim_token == claim_token)
        conditions.append(ReconstructionJob.status == "running")
    result = await db.execute(
        update(ReconstructionJob)
        .where(*conditions)
        .values(status="completed", error=None)
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        await db.commit()
        counter("jobs_stale_results_discarded_total").inc()
        logger.warning("job_stale_result_discarded", job_id=job_id, outcome="complete")
        return False
    job = await db.get(ReconstructionJob, job_id)
    assert job is not None
    await db.execute(
        update(Project)
        .where(Project.id == job.project_id)
        .values(
            status="completed",
            fidelity_score=fidelity,
            completed_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    counter("jobs_completed_total").inc()
    logger.info("job_completed", job_id=job_id, fidelity=fidelity)
    return True


async def fail(
    db: AsyncSession, job_id: int, error: str, claim_token: Optional[str] = None
) -> None:
    """Record a failed attempt; retry (back to pending) until max_attempts.

    Guarded by ``claim_token`` when given: a stale worker's failure report
    for a job that was already requeued/re-claimed is discarded.
    """
    job = await db.get(ReconstructionJob, job_id)
    if job is None:
        return
    if claim_token is not None and (
        str(job.claim_token or "") != claim_token or str(job.status) != "running"
    ):
        counter("jobs_stale_results_discarded_total").inc()
        logger.warning("job_stale_result_discarded", job_id=job_id, outcome="fail")
        return
    if job.attempts >= job.max_attempts:
        await db.execute(
            update(ReconstructionJob)
            .where(ReconstructionJob.id == job_id)
            .values(status="failed", error=error[:2000], claim_token=None)
        )
        await db.execute(
            update(Project).where(Project.id == job.project_id).values(status="failed")
        )
        counter("jobs_failed_total").inc()
        logger.warning("job_failed_permanently", job_id=job_id, attempts=job.attempts)
    else:
        await db.execute(
            update(ReconstructionJob)
            .where(ReconstructionJob.id == job_id)
            .values(status="pending", error=error[:2000], claim_token=None)
        )
        logger.warning("job_failed_will_retry", job_id=job_id, attempts=job.attempts)
    await db.commit()


async def fail_permanent(
    db: AsyncSession, job_id: int, error: str, claim_token: Optional[str] = None
) -> None:
    """Fail a job immediately without retrying (e.g. a compliance block)."""
    job = await db.get(ReconstructionJob, job_id)
    if job is None:
        return
    if claim_token is not None and (
        str(job.claim_token or "") != claim_token or str(job.status) != "running"
    ):
        counter("jobs_stale_results_discarded_total").inc()
        logger.warning("job_stale_result_discarded", job_id=job_id, outcome="permanent")
        return
    await db.execute(
        update(ReconstructionJob)
        .where(ReconstructionJob.id == job_id)
        .values(status="failed", error=error[:2000], claim_token=None)
    )
    await db.execute(
        update(Project).where(Project.id == job.project_id).values(status="failed")
    )
    await db.commit()
    counter("jobs_failed_total").inc()
    logger.warning("job_failed_permanent", job_id=job_id)


async def recover_stale(db: AsyncSession, older_than_seconds: float = 1800) -> int:
    """Requeue jobs whose worker has stopped heartbeating (crashed mid-run).

    Keys off the last heartbeat (``started_at`` for legacy rows without one),
    so a long-running but alive reconstruction is never requeued while a dead
    worker's job is. Clearing ``claim_token`` invalidates the old worker's
    claim: if it is in fact still alive, its late result is discarded by the
    guarded writes above. Returns the number of jobs requeued.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    result = await db.execute(
        update(ReconstructionJob)
        .where(
            ReconstructionJob.status == "running",
            func.coalesce(ReconstructionJob.heartbeat_at, ReconstructionJob.started_at)
            < cutoff,
        )
        .values(status="pending", claim_token=None)
    )
    await db.commit()
    count = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if count:
        logger.info("stale_jobs_recovered", count=count)
    return count
