"""Per-project run isolation: output dirs are never shared across projects."""

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from wire import worker
from wire.api import job_queue
from wire.api.database import Base
from wire.api.main_routes import _project_run_id
from wire.api.models import Project
from wire.storage.local import LocalStorage, sanitize_run_id

# --- LocalStorage naming ------------------------------------------------------


def test_run_id_names_the_directory(tmp_path, monkeypatch):
    storage = LocalStorage()
    storage.base_dir = str(tmp_path)
    storage.initialize_for_url("https://example.com/", run_id="project_42")
    assert storage.current_run_dir == os.path.join(str(tmp_path), "project_42")
    assert os.path.isdir(storage.current_run_dir)


def test_without_run_id_falls_back_to_domain(tmp_path):
    storage = LocalStorage()
    storage.base_dir = str(tmp_path)
    storage.initialize_for_url("https://www.example.com/page")
    assert storage.current_run_dir == os.path.join(str(tmp_path), "example.com")


def test_same_domain_different_projects_get_distinct_dirs(tmp_path):
    # The core multi-tenancy property: two projects for the SAME domain
    # must never share a run directory.
    a, b = LocalStorage(), LocalStorage()
    a.base_dir = b.base_dir = str(tmp_path)
    a.initialize_for_url("https://example.com/", run_id="project_1")
    b.initialize_for_url("https://example.com/", run_id="project_2")
    assert a.current_run_dir != b.current_run_dir


def test_run_id_is_sanitized_against_traversal():
    assert sanitize_run_id("../../etc/passwd") == "passwd"
    # Backslash is not a separator on POSIX; it is neutralized, not split.
    assert sanitize_run_id("a/b\\c") == "b_c"
    assert sanitize_run_id("project 7!") == "project_7"
    assert sanitize_run_id("...") == "run"
    assert sanitize_run_id("") == "run"
    assert sanitize_run_id("project_42") == "project_42"


def test_sanitized_run_id_stays_inside_base_dir(tmp_path):
    storage = LocalStorage()
    storage.base_dir = str(tmp_path)
    storage.initialize_for_url("https://x.com/", run_id="../escape")
    resolved = os.path.realpath(storage.current_run_dir)
    assert resolved.startswith(os.path.realpath(str(tmp_path)))


# --- Worker passes the project-scoped run id ----------------------------------


@pytest.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/jobs.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_runs_with_project_scoped_run_id(session_factory):
    async with session_factory() as db:
        project = Project(url="https://ex.com", status="pending")
        db.add(project)
        await db.commit()
        await db.refresh(project)
        pid = int(project.id)
        await job_queue.enqueue(db, pid, "https://ex.com")

    seen = {}

    async def runner(url, run_id):
        seen["url"], seen["run_id"] = url, run_id
        return 77.0

    assert await worker.process_one(session_factory, runner) is True
    assert seen == {"url": "https://ex.com", "run_id": f"project_{pid}"}


# --- API helper: run_id preferred, legacy fallback ----------------------------


def test_project_run_id_prefers_stored_value():
    project = Project(url="https://example.com/", run_id="project_9")
    assert _project_run_id(project) == "project_9"


def test_project_run_id_legacy_fallback_uses_domain():
    # Pre-migration rows have no run_id; their artifacts live in the old
    # domain-named directory and must still resolve.
    project = Project(url="https://www.example.com/x", run_id=None)
    assert _project_run_id(project) == "example.com"
