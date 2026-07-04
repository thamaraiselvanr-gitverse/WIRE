"""LegalDetector.analyze robots.txt paths, mocked via httpx.MockTransport."""

import httpx
import pytest

import wire.agents.extraction.legal_detector as legal_mod
from wire.agents.extraction.legal_detector import LegalDetector

_RealAsyncClient = httpx.AsyncClient


def _patch_client(monkeypatch, handler):
    def _factory(*a, **k):
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(legal_mod.httpx, "AsyncClient", _factory)


@pytest.mark.asyncio
async def test_disallow_all_marks_restricted(monkeypatch):
    async def handler(request):
        return httpx.Response(200, text="User-agent: *\nDisallow: /")

    _patch_client(monkeypatch, handler)
    result = await LegalDetector().analyze("https://site.test/page")
    assert result["robots_txt"]["found"] is True
    assert result["robots_txt"]["allowed"] is False
    assert result["classification"] == "restricted"


@pytest.mark.asyncio
async def test_permissive_robots_stays_safe(monkeypatch):
    async def handler(request):
        return httpx.Response(200, text="User-agent: *\nDisallow: /admin")

    _patch_client(monkeypatch, handler)
    result = await LegalDetector().analyze("https://site.test/")
    assert result["robots_txt"]["found"] is True
    assert result["robots_txt"]["allowed"] is True
    assert result["classification"] == "safe_to_reconstruct"


@pytest.mark.asyncio
async def test_missing_robots_is_safe(monkeypatch):
    async def handler(request):
        return httpx.Response(404)

    _patch_client(monkeypatch, handler)
    result = await LegalDetector().analyze("https://site.test/")
    assert result["robots_txt"]["found"] is False
    assert result["classification"] == "safe_to_reconstruct"


@pytest.mark.asyncio
async def test_network_error_is_swallowed(monkeypatch):
    async def handler(request):
        raise httpx.ConnectError("no route")

    _patch_client(monkeypatch, handler)
    result = await LegalDetector().analyze("https://unreachable.test/")
    # Failure to fetch robots.txt must not crash; defaults hold.
    assert result["robots_txt"]["found"] is False
    assert result["classification"] == "safe_to_reconstruct"
