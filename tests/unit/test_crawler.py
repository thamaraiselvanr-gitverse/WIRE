import httpx
import pytest

from wire.agents.exploration.crawler import Crawler

PAGES = {
    "https://example.com/": """
        <html><body>
            <a href="/about">About</a>
            <a href="/contact">Contact</a>
            <a href="https://external.com/other">External</a>
        </body></html>
    """,
    "https://example.com/about": """
        <html><body><a href="/">Home</a><a href="/team">Team</a></body></html>
    """,
    "https://example.com/contact": "<html><body>Contact us</body></html>",
    "https://example.com/team": "<html><body>Team page</body></html>",
}

ROBOTS_TXT = "User-agent: *\nDisallow: /contact\n"


async def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("/robots.txt"):
        return httpx.Response(
            200, text=ROBOTS_TXT, headers={"content-type": "text/plain"}
        )
    body = PAGES.get(url)
    if body is None:
        return httpx.Response(404)
    return httpx.Response(200, text=body, headers={"content-type": "text/html"})


@pytest.mark.asyncio
async def test_single_page_crawl_returns_only_input_url():
    crawler = Crawler()
    pages = await crawler.crawl("https://example.com/", single_page=True)
    assert pages == ["https://example.com/"]


@pytest.mark.asyncio
async def test_multi_page_crawl_discovers_same_domain_links_and_respects_robots():
    transport = httpx.MockTransport(_handler)
    crawler = Crawler(max_pages=10, max_depth=2, transport=transport)
    pages = await crawler.crawl("https://example.com/", single_page=False)

    assert "https://example.com/" in pages
    assert any(p.rstrip("/").endswith("/about") for p in pages)
    assert any(p.rstrip("/").endswith("/team") for p in pages)
    # Disallowed by robots.txt — must not be crawled.
    assert not any(p.rstrip("/").endswith("/contact") for p in pages)
    # Off-domain link must never be followed.
    assert not any("external.com" in p for p in pages)


@pytest.mark.asyncio
async def test_multi_page_crawl_respects_max_pages():
    transport = httpx.MockTransport(_handler)
    crawler = Crawler(max_pages=1, max_depth=2, transport=transport)
    pages = await crawler.crawl("https://example.com/", single_page=False)
    assert pages == ["https://example.com/"]


@pytest.mark.asyncio
async def test_multi_page_crawl_respects_max_depth():
    transport = httpx.MockTransport(_handler)
    crawler = Crawler(max_pages=10, max_depth=0, transport=transport)
    pages = await crawler.crawl("https://example.com/", single_page=False)
    assert pages == ["https://example.com/"]
