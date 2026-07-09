"""BehavioralExtractor degradation paths — a fake page whose calls all raise
exercises every fail-closed branch without a real browser."""

import pytest

from wire.agents.extraction.behavioral_extractor import BehavioralExtractor


class _Mouse:
    async def move(self, *a, **k):
        pass


class _FakePage:
    viewport_size = {"width": 800, "height": 600}
    mouse = _Mouse()

    async def evaluate(self, *a, **k):
        raise RuntimeError("evaluate failed")

    async def eval_on_selector(self, *a, **k):
        raise RuntimeError("selector failed")

    async def query_selector(self, *a, **k):
        raise RuntimeError("query failed")

    async def hover(self, *a, **k):
        raise RuntimeError("hover failed")

    async def focus(self, *a, **k):
        raise RuntimeError("focus failed")

    async def wait_for_timeout(self, *a, **k):
        pass


@pytest.mark.asyncio
async def test_extract_degrades_gracefully_when_everything_fails():
    report = await BehavioralExtractor().extract(_FakePage(), deep=True)

    # Library probe failed -> recorded as an error, not a crash.
    assert "error" in report
    # No interaction states could be sampled.
    assert report["interaction_states"] == []
    # Scroll detection failed closed.
    assert report["scroll_animations"]["revealed_on_scroll"] == 0
    # Deep probes failed closed too.
    assert report["carousel_timing"]["detected"] is False
    assert report["timed_triggers"]["exit_intent_modal"] is False
    assert report["timed_triggers"]["delayed_content_injected"] is False


def test_delta_helper_direct():
    d = BehavioralExtractor._delta({"color": "a"}, {"color": "b"})
    assert d == {"color": {"from": "a", "to": "b"}}
