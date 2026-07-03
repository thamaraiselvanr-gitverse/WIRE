import urllib.parse
import urllib.robotparser
from typing import Optional

import httpx
import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger(__name__)


class Crawler:
    """
    Same-domain link discovery. `single_page=True` (the Phase 1 MVP default)
    returns just the input URL. `single_page=False` performs a breadth-first
    crawl of same-domain links, honoring robots.txt, bounded by max_pages/max_depth.
    """

    def __init__(
        self,
        max_pages: int = 25,
        max_depth: int = 2,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.max_pages = max_pages
        self.max_depth = max_depth
        self._transport = transport

    async def crawl(self, url: str, single_page: bool = False) -> list[str]:
        logger.info(
            "starting_crawl", url=url, type="single_page" if single_page else "full"
        )
        if single_page:
            return [url]
        return await self._crawl_domain(url)

    async def _crawl_domain(self, start_url: str) -> list[str]:
        parsed_start = urllib.parse.urlparse(start_url)
        domain = parsed_start.netloc

        async with httpx.AsyncClient(
            transport=self._transport, follow_redirects=True, timeout=15.0
        ) as client:
            robots = await self._load_robots(client, parsed_start)

            visited: set[str] = set()
            queue: list[tuple[str, int]] = [(start_url, 0)]
            discovered: list[str] = []

            while queue and len(discovered) < self.max_pages:
                page_url, depth = queue.pop(0)
                normalized = self._normalize(page_url)
                if normalized in visited:
                    continue
                visited.add(normalized)

                if robots is not None and not robots.can_fetch("*", page_url):
                    logger.info("crawl_skipped_by_robots", url=page_url)
                    continue

                discovered.append(page_url)

                if depth >= self.max_depth:
                    continue

                try:
                    resp = await client.get(page_url)
                    content_type = resp.headers.get("content-type", "")
                    if resp.status_code != 200 or "text/html" not in content_type:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    for tag in soup.find_all("a", href=True):
                        link = urllib.parse.urljoin(page_url, tag["href"]).split(
                            "#", 1
                        )[0]
                        link_parsed = urllib.parse.urlparse(link)
                        if link_parsed.netloc != domain or link_parsed.scheme not in (
                            "http",
                            "https",
                        ):
                            continue
                        if self._normalize(link) not in visited:
                            queue.append((link, depth + 1))
                except Exception as e:
                    logger.warning(
                        "crawl_page_fetch_failed", url=page_url, error=str(e)
                    )

        logger.info("crawl_completed", pages_found=len(discovered))
        return discovered

    @staticmethod
    def _normalize(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    @staticmethod
    async def _load_robots(
        client: httpx.AsyncClient, parsed_start: urllib.parse.ParseResult
    ) -> Optional[urllib.robotparser.RobotFileParser]:
        robots_url = f"{parsed_start.scheme}://{parsed_start.netloc}/robots.txt"
        try:
            resp = await client.get(robots_url)
            if resp.status_code == 200:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(resp.text.splitlines())
                return parser
        except Exception as e:
            logger.warning("robots_txt_fetch_failed", url=robots_url, error=str(e))
        return None
