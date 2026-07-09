from unittest.mock import AsyncMock, MagicMock

import pytest

from wire.agents.exploration.region_probe import RegionProbe


@pytest.mark.asyncio
async def test_region_probe_proxy_and_context_arguments():
    probe = RegionProbe()

    # Mock Playwright classes
    mock_page = AsyncMock()
    mock_page.title.return_value = "Test Title"
    mock_page.content.return_value = "<html>Mock Content</html>"

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    proxies = {
        "us-east": {"server": "http://us-east.proxy.com:8080"},
        "eu-west": {"server": "http://eu-west.proxy.com:8080"},
    }

    # Run region capture
    results = await probe.capture_regions(
        mock_browser,
        url="http://example.com",
        asset_dir="output",
        proxies=proxies,
    )

    # 1. Verify all configured regions are present
    assert set(results.keys()) == {"us-east", "eu-west", "ap-south"}

    # 2. Check that new_context was called with correct locale/timezone/proxy configs
    # We should have 3 calls to new_context
    assert mock_browser.new_context.call_count == 3

    calls = mock_browser.new_context.call_args_list

    # Match us-east context call
    us_east_call = next(
        c for c in calls if c.kwargs.get("timezone_id") == "America/New_York"
    )
    assert us_east_call.kwargs["locale"] == "en-US"
    assert us_east_call.kwargs["proxy"] == {"server": "http://us-east.proxy.com:8080"}

    # Match ap-south context call (no proxy)
    ap_south_call = next(
        c for c in calls if c.kwargs.get("timezone_id") == "Asia/Kolkata"
    )
    assert ap_south_call.kwargs["locale"] == "en-IN"
    assert "proxy" not in ap_south_call.kwargs
