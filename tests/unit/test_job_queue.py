"""Durable job queue + worker: enqueue, claim, complete, retry/fail, recovery."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from wire import worker
from wire.api import job_queue
from wire.api.database import Base
from wire.api.models import Project, ReconstructionJob


@pytest.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/jobs.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _make_project(factory, url="https://ex.com") -> int:
    async with factory() as db:
        p = Project(url=url, status="pending")
        db.add(p)
        await db.commit()
        await db.refresh(p)
        return int(p.id)


@pytest.mark.asyncio
async def test_enqueue_and_claim(session_factory):
    pid = await _make_project(session_factory)
    async with session_factory() as db:
        job = await job_queue.enqueue(db, pid, "https://ex.com")
        assert job.status == "pending"

    async with session_factory() as db:
        claimed = await job_queue.claim_next(db)
        assert claimed is not None
        assert claimed.status == "running" and claimed.attempts == 1

    # No more pending jobs.
    async with session_factory() as db:
        assert await job_queue.claim_next(db) is None


@pytest.mark.asyncio
async def test_worker_completes_job(session_factory):
    pid = await _make_project(session_factory)
    async with session_factory() as db:
        await job_queue.enqueue(db, pid, "https://ex.com")

    async def runner(url):
        return 88.0

    processed = await worker.process_one(session_factory, runner)
    assert processed is True

    async with session_factory() as db:
        job = (await db.execute(_all(ReconstructionJob))).scalars().first()
        proj = await db.get(Project, pid)
        assert job.status == "completed"
        assert proj.status == "completed" and proj.fidelity_score == 88.0


@pytest.mark.asyncio
async def test_process_one_empty_queue_returns_false(session_factory):
    async def runner(url):
        return 1.0

    assert await worker.process_one(session_factory, runner) is False


@pytest.mark.asyncio
async def test_worker_retries_then_fails(session_factory):
    pid = await _make_project(session_factory)
    async with session_factory() as db:
        job = ReconstructionJob(
            project_id=pid, url="https://ex.com", status="pending", max_attempts=2
        )
        db.add(job)
        await db.commit()

    async def failing(url):
        raise RuntimeError("pipeline boom")

    # First failure -> retried (back to pending).
    await worker.process_one(session_factory, failing)
    async with session_factory() as db:
        job = (await db.execute(_all(ReconstructionJob))).scalars().first()
        assert job.status == "pending" and job.attempts == 1

    # Second failure hits max_attempts -> permanently failed, project failed.
    await worker.process_one(session_factory, failing)
    async with session_factory() as db:
        job = (await db.execute(_all(ReconstructionJob))).scalars().first()
        proj = await db.get(Project, pid)
        assert job.status == "failed" and job.attempts == 2
        assert "boom" in (job.error or "")
        assert proj.status == "failed"


@pytest.mark.asyncio
async def test_recover_stale_requeues_running_jobs(session_factory):
    pid = await _make_project(session_factory)
    async with session_factory() as db:
        stale = ReconstructionJob(
            project_id=pid,
            url="https://ex.com",
            status="running",
            started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db.add(stale)
        await db.commit()

    async with session_factory() as db:
        recovered = await job_queue.recover_stale(db, older_than_seconds=60)
        assert recovered == 1

    async with session_factory() as db:
        job = (await db.execute(_all(ReconstructionJob))).scalars().first()
        assert job.status == "pending"


@pytest.mark.asyncio
async def test_run_worker_bounded_drains_queue(session_factory):
    pid = await _make_project(session_factory)
    async with session_factory() as db:
        await job_queue.enqueue(db, pid, "https://ex.com")

    async def runner(url):
        return 50.0

    # A couple of iterations is enough to claim + finalize the one job.
    await worker.run_worker(
        session_factory, runner=runner, poll_interval=0, max_iterations=3
    )
    async with session_factory() as db:
        job = (await db.execute(_all(ReconstructionJob))).scalars().first()
        assert job.status == "completed"


@pytest.mark.asyncio
async def test_worker_compliance_error_fails_permanently(session_factory):
    from wire.utils.errors import ComplianceError

    pid = await _make_project(session_factory)
    async with session_factory() as db:
        # max_attempts high — a compliance block must still fail immediately.
        job = ReconstructionJob(
            project_id=pid, url="https://x.test", status="pending", max_attempts=5
        )
        db.add(job)
        await db.commit()

    async def blocked(url):
        raise ComplianceError("robots.txt disallows")

    await worker.process_one(session_factory, blocked)
    async with session_factory() as db:
        job = (await db.execute(_all(ReconstructionJob))).scalars().first()
        proj = await db.get(Project, pid)
        assert job.status == "failed" and job.attempts == 1  # no retry
        assert proj.status == "failed"


def _all(model):
    from sqlalchemy import select

    return select(model)
