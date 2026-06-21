import structlog

logger = structlog.get_logger(__name__)

class Crawler:
    async def crawl(self, url: str, single_page: bool = False) -> list[str]:
        logger.info("starting_crawl", url=url, type="single_page" if single_page else "full")
        # For Phase 1, MVP single page crawl simply returns the root URL
        if single_page:
            return [url]
        return [url]
