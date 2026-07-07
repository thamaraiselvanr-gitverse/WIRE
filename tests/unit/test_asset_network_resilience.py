"""Network resilience: retry + backoff + Retry-After on transient failures."""

import httpx
import pytest

from wire.agents.extraction.asset_downloader import AssetDownloader


class _Resp:
    def __init__(self, status=200, content=b"ok", headers=None):
        self.status_code = status
        self.content = content
        self.text = content.decode(errors="ignore")
        self.headers = headers or {}


class _ScriptedClient:
    """Returns queued responses/exceptions in order, per URL."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def get(self, url, follow_redirects=False):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Record backoff delays without actually sleeping.
    delays = []

    async def _fake_sleep(d):
        delays.append(d)

    monkeypatch.setattr(
        "wire.agents.extraction.asset_downloader.asyncio.sleep", _fake_sleep
    )
    return delays


@pytest.mark.asyncio
async def test_retries_on_500_then_succeeds():
    dl = AssetDownloader()
    dl.client = _ScriptedClient([_Resp(500), _Resp(502), _Resp(200, b"good")])
    resp = await dl._fetch("https://x/a.css")
    assert resp is not None and resp.status_code == 200
    assert resp.content == b"good"
    assert dl.client.calls == 3


@pytest.mark.asyncio
async def test_retries_on_network_exception_then_succeeds():
    dl = AssetDownloader()
    dl.client = _ScriptedClient([httpx.ConnectError("boom"), _Resp(200, b"recovered")])
    resp = await dl._fetch("https://x/a.png")
    assert resp is not None and resp.status_code == 200
    assert dl.client.calls == 2


@pytest.mark.asyncio
async def test_permanent_404_not_retried():
    dl = AssetDownloader()
    dl.client = _ScriptedClient([_Resp(404)])
    resp = await dl._fetch("https://x/missing.png")
    assert resp is not None and resp.status_code == 404
    assert dl.client.calls == 1  # returned immediately, no retry


@pytest.mark.asyncio
async def test_gives_up_after_max_retries():
    dl = AssetDownloader()
    dl.client = _ScriptedClient([_Resp(503)] * (dl.MAX_RETRIES + 1))
    resp = await dl._fetch("https://x/rate.css")
    assert resp is not None and resp.status_code == 503
    assert dl.client.calls == dl.MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_all_attempts_raise_returns_none():
    dl = AssetDownloader()
    dl.client = _ScriptedClient([httpx.ConnectError("x")] * (dl.MAX_RETRIES + 1))
    resp = await dl._fetch("https://x/dead.png")
    assert resp is None


@pytest.mark.asyncio
async def test_retry_after_header_is_honored(_no_sleep):
    dl = AssetDownloader()
    dl.client = _ScriptedClient([_Resp(429, headers={"Retry-After": "2"}), _Resp(200)])
    resp = await dl._fetch("https://x/a.js")
    assert resp is not None and resp.status_code == 200
    # The first (and only) backoff used the Retry-After value exactly.
    assert _no_sleep == [2.0]


def test_retry_delay_backoff_and_cap():
    dl = AssetDownloader()
    # No response -> exponential backoff with jitter, within [base*2^n, *1.25].
    d0 = dl._retry_delay(0, None)
    assert dl.BACKOFF_BASE <= d0 <= dl.BACKOFF_BASE * 1.25
    # Large attempt is capped at MAX_BACKOFF (+jitter).
    d_big = dl._retry_delay(10, None)
    assert d_big <= dl.MAX_BACKOFF * 1.25


@pytest.mark.asyncio
async def test_non_numeric_retry_after_falls_back_to_backoff(_no_sleep):
    dl = AssetDownloader()
    dl.client = _ScriptedClient(
        [
            _Resp(503, headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"}),
            _Resp(200),
        ]
    )
    resp = await dl._fetch("https://x/a.css")
    assert resp is not None and resp.status_code == 200
    # HTTP-date not parsed -> fell back to exponential backoff (>0, not a date).
    assert len(_no_sleep) == 1 and _no_sleep[0] <= dl.MAX_BACKOFF * 1.25
