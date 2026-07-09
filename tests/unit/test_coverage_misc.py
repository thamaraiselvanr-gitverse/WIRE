import pytest

from wire.agents.extraction.legal_detector import LegalDetector
from wire.agents.extraction.network_monitor import NetworkMonitor
from wire.semantic.llm_client import LLMClient


def test_llm_client_without_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    client = LLMClient()
    assert client.is_available is False
    # generate_json fails closed (returns None) when unavailable.
    assert client.generate_json("sys", "user") is None


def test_network_monitor_report_from_captured():
    nm = NetworkMonitor()
    nm.captured_requests = [
        {"url": "http://x/a.js", "method": "GET", "resource_type": "script"},
        {"url": "http://x/b.css", "method": "GET", "resource_type": "stylesheet"},
        {"url": "http://x/api/data", "method": "GET", "resource_type": "fetch"},
    ]
    nm.api_endpoints = [{"url": "http://x/api/data", "status": 200}]
    nm.dynamic_data = [{"url": "http://x/api/data", "type": "fetch"}]
    report = nm.get_report()
    assert report["total_requests"] == 3
    assert report["resource_breakdown"]["script"] == 1
    assert len(report["api_endpoints"]) == 1
    assert len(report["dynamic_data_sources"]) == 1


@pytest.mark.asyncio
async def test_legal_detector_handles_unreachable_gracefully():
    # A file:// URL has no host, so the robots.txt fetch fails and the detector
    # falls back to its safe-by-default classification without raising.
    result = await LegalDetector().analyze("file:///tmp/whatever.html")
    assert result["classification"] in ("safe_to_reconstruct", "restricted")
    assert result["robots_txt"]["found"] is False
