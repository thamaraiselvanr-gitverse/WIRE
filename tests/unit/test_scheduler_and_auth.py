"""Bounded-concurrency scheduler + auth-primitive unit tests (no browser)."""

import asyncio

import pytest

from wire.agents.observation.auth_handler import AuthHandler
from wire.orchestrator.scheduler import TaskScheduler


@pytest.mark.asyncio
async def test_scheduler_caps_concurrency():
    sched = TaskScheduler(max_concurrency=3)
    live = {"now": 0, "peak": 0}

    async def job(i):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0.01)
        live["now"] -= 1
        return i * 2

    results = await sched.run_all([job(i) for i in range(12)])

    # Order preserved, all ran, and the ceiling was respected.
    assert results == [i * 2 for i in range(12)]
    assert live["peak"] <= 3
    assert sched.peak_concurrency <= 3
    assert sched.peak_concurrency >= 1


@pytest.mark.asyncio
async def test_scheduler_empty_batch():
    assert await TaskScheduler().run_all([]) == []


@pytest.mark.asyncio
async def test_scheduler_single_schedule_still_works():
    async def one():
        return 42

    assert await TaskScheduler().schedule(one()) == 42


def test_basic_auth_args():
    args = AuthHandler.basic_auth_args("neo", "trinity")
    assert args == {"http_credentials": {"username": "neo", "password": "trinity"}}


def test_build_storage_state_shape():
    state = AuthHandler.build_storage_state(
        cookies=[{"name": "sid", "value": "x", "domain": "a.com", "path": "/"}],
        origins=[
            {"origin": "https://a.com", "localStorage": [{"name": "t", "value": "1"}]}
        ],
    )
    assert state["cookies"][0]["name"] == "sid"
    assert state["origins"][0]["origin"] == "https://a.com"


def test_build_storage_state_defaults_empty():
    assert AuthHandler.build_storage_state() == {"cookies": [], "origins": []}
