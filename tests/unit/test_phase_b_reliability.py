"""Phase B: Redis limiter, worker claim guards/heartbeat, latency metrics."""

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from wire import worker
from wire.api import job_queue, metrics
from wire.api.database import Base
from wire.api.models import Project, ReconstructionJob
from wire.api.rate_limit import RateLimiter, RedisRateLimiter, build_limiter

# --- B1: Redis-backed rate limiting -------------------------------------------


class _FakeRedis:
    """In-memory stand-in implementing the two commands the limiter uses."""

    def __init__(self, fail=False):
        self.fail = fail
        self.store = {}
        self.expires = {}

    def incr(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key, seconds):
        self.expires[key] = seconds


def test_redis_limiter_allows_up_to_budget_then_429():
    fake = _FakeRedis()
    limiter = RedisRateLimiter(max_requests=3, window_seconds=60, client=fake)
    for _ in range(3):
        limiter.check("user:1")
    with pytest.raises(HTTPException) as exc:
        limiter.check("user:1")
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers
    # The window bucket got a TTL so keys don't accumulate forever.
    assert list(fake.expires.values()) == [60]


def test_redis_limiter_keys_are_isolated():
    limiter = RedisRateLimiter(max_requests=1, window_seconds=60, client=_FakeRedis())
    limiter.check("user:1")
    limiter.check("user:2")  # different key, own budget
    with pytest.raises(HTTPException):
        limiter.check("user:1")


def test_redis_limiter_fails_open_when_redis_unreachable():
    limiter = RedisRateLimiter(
        max_requests=1, window_seconds=60, client=_FakeRedis(fail=True)
    )
    # Abuse control must not take the product down with it.
    for _ in range(5):
        limiter.check("user:1")


def test_build_limiter_selects_backend_by_env(monkeypatch):
    monkeypatch.delenv("WIRE_REDIS_URL", raising=False)
    assert isinstance(build_limiter(5, 60, "t"), RateLimiter)
    monkeypatch.setenv("WIRE_REDIS_URL", "redis://localhost:6379/0")
    assert isinstance(build_limiter(5, 60, "t"), RedisRateLimiter)


def test_memory_limiter_prunes_idle_keys(monkeypatch):
    limiter = RateLimiter(max_requests=5, window_seconds=0.0)
    limiter.check("gone")
    # Force the prune pass on the next check (window elapsed).
    limiter._last_prune -= 1
    limiter.check("fresh")
    assert "gone" not in limiter._hits


# --- B4: claim guards + heartbeat ----------------------------------------------


@pytest.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/jobs.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_job(factory) -> int:
    async with factory() as db:
        p = Project(url="https://ex.com", status="pending")
        db.add(p)
        await db.commit()
        await db.refresh(p)
        await job_queue.enqueue(db, int(p.id), "https://ex.com")
        return int(p.id)


@pytest.mark.asyncio
async def test_claim_sets_token_and_heartbeat(session_factory):
    await _seed_job(session_factory)
    async with session_factory() as db:
        job = await job_queue.claim_next(db)
        assert job is not None
        assert job.claim_token and len(str(job.claim_token)) == 32
        assert job.heartbeat_at is not None


@pytest.mark.asyncio
async def test_heartbeat_reports_lost_claim_after_recovery(session_factory):
    await _seed_job(session_factory)
    async with session_factory() as db:
        job = await job_queue.claim_next(db)
        job_id, token = int(job.id), str(job.claim_token)

    async with session_factory() as db:
        assert await job_queue.heartbeat(db, job_id, token) is True
        # Everything running is "stale" at cutoff 0 -> requeued, claim cleared.
        assert await job_queue.recover_stale(db, older_than_seconds=-1) == 1
        assert await job_queue.heartbeat(db, job_id, token) is False


@pytest.mark.asyncio
async def test_stale_worker_result_is_discarded_not_double_written(session_factory):
    """The double-run race: worker1 wedges, job is requeued, worker2 finishes,
    then worker1 wakes up and reports — its late result must be discarded."""
    pid = await _seed_job(session_factory)

    async with session_factory() as db:
        job1 = await job_queue.claim_next(db)
        job_id, token1 = int(job1.id), str(job1.claim_token)

    # Stale recovery requeues; worker2 claims and completes with fidelity 90.
    async with session_factory() as db:
        await job_queue.recover_stale(db, older_than_seconds=-1)
    async with session_factory() as db:
        job2 = await job_queue.claim_next(db)
        token2 = str(job2.claim_token)
        assert token2 != token1
    async with session_factory() as db:
        assert await job_queue.complete(db, job_id, 90.0, token2) is True

    # Worker1's zombie result: discarded, project untouched.
    async with session_factory() as db:
        assert await job_queue.complete(db, job_id, 10.0, token1) is False
        proj = await db.get(Project, pid)
        assert proj.fidelity_score == 90.0 and proj.status == "completed"

    # Same for a zombie failure report.
    async with session_factory() as db:
        await job_queue.fail(db, job_id, "zombie says boom", token1)
        job = await db.get(ReconstructionJob, job_id)
        proj = await db.get(Project, pid)
        assert job.status == "completed" and proj.status == "completed"


@pytest.mark.asyncio
async def test_worker_heartbeats_while_running(session_factory):
    import asyncio

    await _seed_job(session_factory)
    beats = []
    real_heartbeat = job_queue.heartbeat

    async def spying_heartbeat(db, job_id, token):
        beats.append(job_id)
        return await real_heartbeat(db, job_id, token)

    job_queue.heartbeat = spying_heartbeat
    try:

        async def slow_runner(url, run_id):
            await asyncio.sleep(0.15)
            return 42.0

        assert (
            await worker.process_one(
                session_factory, slow_runner, heartbeat_interval=0.05
            )
            is True
        )
    finally:
        job_queue.heartbeat = real_heartbeat
    assert len(beats) >= 1  # kept the claim fresh during the run


@pytest.mark.asyncio
async def test_recover_stale_respects_fresh_heartbeat(session_factory):
    await _seed_job(session_factory)
    async with session_factory() as db:
        await job_queue.claim_next(db)
    async with session_factory() as db:
        # Heartbeat is fresh (set at claim) -> a sane cutoff requeues nothing.
        assert await job_queue.recover_stale(db, older_than_seconds=3600) == 0


# --- B6: latency metrics --------------------------------------------------------


def test_histogram_renders_prometheus_exposition():
    metrics.reset()
    h = metrics.histogram("test_duration_seconds")
    h.observe(0.3)
    h.observe(7.0)
    h.observe(9999.0)  # beyond the largest bucket -> only +Inf
    out = metrics.render_prometheus()
    assert "# TYPE wire_test_duration_seconds histogram" in out
    assert 'wire_test_duration_seconds_bucket{le="0.5"} 1' in out
    assert 'wire_test_duration_seconds_bucket{le="10"} 2' in out
    assert 'wire_test_duration_seconds_bucket{le="+Inf"} 3' in out
    assert "wire_test_duration_seconds_count 3" in out
    metrics.reset()


@pytest.mark.asyncio
async def test_pipeline_duration_observed(session_factory):
    metrics.reset()
    await _seed_job(session_factory)

    async def runner(url, run_id):
        return 50.0

    await worker.process_one(session_factory, runner)
    assert metrics.histogram("pipeline_duration_seconds").count == 1
    metrics.reset()
