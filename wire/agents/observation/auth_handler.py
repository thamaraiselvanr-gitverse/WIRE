import structlog
from playwright.async_api import BrowserContext

logger = structlog.get_logger(__name__)

class AuthHandler:
    @staticmethod
    async def inject_session(context: BrowserContext, cookies: list[dict]) -> None:
        """
        Dual-mode authentication: Phase 2 MVP supports manual session cookie injection.
        """
        logger.info("injecting_session_cookies", count=len(cookies))
        if cookies:
            await context.add_cookies(cookies)
