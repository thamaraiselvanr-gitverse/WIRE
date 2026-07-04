"""Durable, DB-backed reconstruction job queue.

Persisting jobs (rather than firing ``asyncio.create_task``) makes the pipeline
resilient: work survives an API restart, is retried on failure, and can be
processed by one or more separate worker processes. Jobs are claimed with an
optimistic ``UPDATE … WHERE status='pending'`` guard, which is safe across
concurrent workers on both SQLite and PostgreSQL without a broker.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Project, ReconstructionJob

logger = structlog.get_logger(__name__)


async def enqueue(db: AsyncSession, project_id: int, url: str) -> ReconstructionJob:
    """Persist a new pending job for ``project_id``."""
    job = ReconstructionJob(project_id=project_id, url=url, status="pending")
    db.add(job)
    await db.commit()
    await db.refresh(job)
    logger.info("job_enqueued", job_id=job.id, project_id=project_id)
    return job


async def claim_next(db: AsyncSession) -> Optional[ReconstructionJob]:
    """Atomically claim the oldest pending job (pending -> running).

    Returns the claimed job, or None if the queue is empty or another worker
    won the race for the candidate job.
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

    claimed = await db.execute(
        update(ReconstructionJob)
        .where(
            ReconstructionJob.id == job.id,
            ReconstructionJob.status == "pending",
        )
        .values(
            status="running",
            attempts=ReconstructionJob.attempts + 1,
            started_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    if claimed.rowcount == 0:  # type: ignore[attr-defined]
        return None  # lost the race to another worker
    await db.refresh(job)
    logger.info("job_claimed", job_id=job.id, attempt=job.attempts)
    return job


async def complete(db: AsyncSession, job_id: int, fidelity: float) -> None:
    """Mark a job (and its project) completed."""
    job = await db.get(ReconstructionJob, job_id)
    if job is None:
        return
    await db.execute(
        update(ReconstructionJob)
        .where(ReconstructionJob.id == job_id)
        .values(status="completed", error=None)
    )
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
    logger.info("job_completed", job_id=job_id, fidelity=fidelity)


async def fail(db: AsyncSession, job_id: int, error: str) -> None:
    """Record a failed attempt; retry (back to pending) until max_attempts."""
    job = await db.get(ReconstructionJob, job_id)
    if job is None:
        return
    if job.attempts >= job.max_attempts:
        await db.execute(
            update(ReconstructionJob)
            .where(ReconstructionJob.id == job_id)
            .values(status="failed", error=error[:2000])
        )
        await db.execute(
            update(Project).where(Project.id == job.project_id).values(status="failed")
        )
        logger.warning("job_failed_permanently", job_id=job_id, attempts=job.attempts)
    else:
        await db.execute(
            update(ReconstructionJob)
            .where(ReconstructionJob.id == job_id)
            .values(status="pending", error=error[:2000])
        )
        logger.warning("job_failed_will_retry", job_id=job_id, attempts=job.attempts)
    await db.commit()


async def recover_stale(db: AsyncSession, older_than_seconds: float = 1800) -> int:
    """Requeue jobs stuck in ``running`` (e.g. a worker crashed mid-run).

    Returns the number of jobs requeued.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    result = await db.execute(
        update(ReconstructionJob)
        .where(
            ReconstructionJob.status == "running",
            ReconstructionJob.started_at < cutoff,
        )
        .values(status="pending")
    )
    await db.commit()
    count = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if count:
        logger.info("stale_jobs_recovered", count=count)
    return count
