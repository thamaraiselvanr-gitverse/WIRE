"""Lazy-content scroll trigger fires before capture (no real browser)."""

import pytest

from wire.agents.observation.browser_session import BrowserSession


class _FakePage:
    """Records evaluate() calls; reports a fixed scrollHeight."""

    def __init__(self, scroll_height=3000):
        self.scroll_height = scroll_height
        self.evals = []
        self.waits = []

    async def evaluate(self, script):
        self.evals.append(script)
        if "scrollHeight" in script and "scrollTo" not in script:
            return self.scroll_height
        return None

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)


@pytest.mark.asyncio
async def test_scrolls_through_page_then_returns_to_top():
    session = BrowserSession()
    page = _FakePage(scroll_height=3000)
    await session.trigger_lazy_content(page, step_px=800)
    scrolls = [e for e in page.evals if "scrollTo" in e]
    # Stepped down the page (3000/800 -> 4 steps), then bottom, then top.
    assert len(scrolls) >= 4
    assert scrolls[-1].endswith("window.scrollTo(0, 0)")
    assert any("document.body.scrollHeight" in s for s in scrolls)


@pytest.mark.asyncio
async def test_step_count_is_capped():
    session = BrowserSession()
    page = _FakePage(scroll_height=10_000_000)  # infinite-scroll style page
    await session.trigger_lazy_content(page, step_px=800, max_steps=40)
    scrolls = [e for e in page.evals if "scrollTo" in e]
    assert len(scrolls) <= 42  # 40 steps + bottom + top


@pytest.mark.asyncio
async def test_scroll_failure_is_swallowed():
    session = BrowserSession()

    class _BrokenPage:
        async def evaluate(self, script):
            raise RuntimeError("page crashed")

        async def wait_for_timeout(self, ms):
            pass

    # Best-effort: capture must proceed even if scrolling throws.
    await session.trigger_lazy_content(_BrokenPage())
