from typing import Optional

import structlog
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from wire.agents.observation.auth_handler import AuthHandler
from wire.agents.observation.stealth import StealthManager
from wire.utils.config import get_config

logger = structlog.get_logger(__name__)


class BrowserSession:
    def __init__(self, credentials: Optional[dict] = None):
        self.config = get_config()
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self._is_active = False
        # Optional operator-supplied auth (cookies/headers/storage) applied at
        # context creation for capturing pages behind a login.
        self.credentials = credentials

    async def start(self) -> None:
        logger.info("starting_playwright_session")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.config.headless
        )
        context_args = {
            "user_agent": self.config.user_agent,
            "viewport": {"width": 1920, "height": 1080},
            **StealthManager.context_fingerprint(),
        }
        self.context = await self.browser.new_context(**context_args)
        await StealthManager.apply_stealth(self.context)
        if self.credentials:
            await AuthHandler.authenticate(self.context, self.credentials)
        await self.context.add_init_script("""
            const originalAttachShadow = Element.prototype.attachShadow;
            Element.prototype.attachShadow = function(init) {
                const shadowRoot = originalAttachShadow.call(this, init);
                this.__wire_shadow_root_ref__ = shadowRoot;
                return shadowRoot;
            };
        """)
        self._is_active = True

    async def wait_for_dom_stability(
        self, page: Page, timeout_ms: int = 5000, check_interval_ms: int = 300
    ) -> None:
        logger.info("waiting_for_dom_stability", timeout=timeout_ms)
        import time

        max_wait = timeout_ms / 1000.0
        last_state = None
        t0 = time.time()

        while time.time() - t0 < max_wait:
            try:
                state = await page.evaluate(
                    "() => [document.body.innerHTML.length, document.querySelectorAll('*').length]"
                )
                if last_state == state:
                    logger.info("dom_stabilized", elapsed=round(time.time() - t0, 2))
                    break
                last_state = state
            except Exception as e:
                logger.warning("dom_stability_check_failed", error=str(e))
            await page.wait_for_timeout(check_interval_ms)

    async def capture_page(self, url: str) -> str:
        if not self._is_active:
            raise RuntimeError("Browser session not started")

        logger.info("capturing_page", url=url)
        page: Page = await self.context.new_page()
        try:
            await page.goto(
                url, wait_until="networkidle", timeout=self.config.timeout_ms
            )

            # Run SPA detection check inline to see if we should wait for stability
            from wire.agents.observation.spa_detector import SPADetector

            detector = SPADetector()
            spa_result = await detector.detect(page)
            if spa_result.get("is_spa"):
                logger.info("spa_detected_waiting_for_hydration")
                await self.wait_for_dom_stability(page)

            # Normalize modals and stuck DOM state before capture
            await page.evaluate("""
                document.querySelectorAll('.modal.show').forEach(el => {
                    el.classList.remove('show');
                    el.style.display = 'none';
                });
                document.querySelectorAll('.modal-backdrop').forEach(el => el.remove());
                document.body.classList.remove('modal-open');
                document.body.style.overflow = '';
                document.body.style.paddingRight = '';
            """)

            content = await page.content()
            return content
        except Exception as e:
            logger.error("page_capture_failed", url=url, error=str(e))
            raise
        finally:
            await page.close()

    async def stop(self) -> None:
        if self._is_active:
            logger.info("stopping_playwright_session")
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            self._is_active = False
