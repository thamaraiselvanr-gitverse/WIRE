import pytest

from wire.orchestrator.checkpointing import CheckpointManager
from wire.orchestrator.coordinator import Coordinator
from wire.orchestrator.scheduler import TaskScheduler
from wire.orchestrator.semantic_merger import SemanticMerger


def test_checkpoint_save_load_mark_clear(tmp_path):
    cp = CheckpointManager(str(tmp_path / "ckpt"))
    assert cp.load() is None  # nothing yet

    state = {"target_url": "http://x", "completed_pages": []}
    state = cp.mark_page_done(state, "http://x/a")
    assert cp.is_page_done(state, "http://x/a")
    assert not cp.is_page_done(state, "http://x/b")
    # marking the same page again is idempotent
    state = cp.mark_page_done(state, "http://x/a")
    assert state["completed_pages"].count("http://x/a") == 1

    loaded = cp.load()
    assert loaded is not None
    assert "http://x/a" in loaded["completed_pages"]

    cp.clear()
    assert cp.load() is None
    cp.clear()  # clearing when absent is a no-op


def test_semantic_merger_dedups_assets():
    merged = SemanticMerger().merge_page_results(
        [
            {"page": "p1", "assets": ["a", "b"], "interactions": [1], "errors": []},
            {"page": "p2", "assets": ["b", "c"], "interactions": [], "errors": ["e"]},
        ]
    )
    assert merged["pages"] == ["p1", "p2"]
    assert merged["assets"] == ["a", "b", "c"]  # deduped, order preserved
    assert merged["interactions"] == [1]
    assert merged["errors"] == ["e"]


def test_coordinator_lock_lifecycle():
    c = Coordinator()
    assert c.acquire_lock("r1") is True
    assert c.acquire_lock("r1") is False  # already held
    c.release_lock("r1")
    assert c.acquire_lock("r1") is True
    c.release_lock("nonexistent")  # no error


@pytest.mark.asyncio
async def test_scheduler_runs_coroutine_and_tracks_active():
    sched = TaskScheduler()

    async def work():
        assert sched.active_tasks == 1
        return 42

    result = await sched.schedule(work())
    assert result == 42
    assert sched.active_tasks == 0
