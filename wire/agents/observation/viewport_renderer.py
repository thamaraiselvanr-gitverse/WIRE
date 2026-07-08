import os
from typing import Any, Dict

import structlog
from playwright.async_api import Page

from wire.storage.local import LocalStorage

logger = structlog.get_logger(__name__)


class ViewportRenderer:
    # tablet (768) and mobile_small (480) match ComputedStyleCapturer's
    # DEFAULT_BREAKPOINTS so per-breakpoint visual validation compares the
    # reconstruction at exactly the widths the responsive capture claims to
    # reproduce. mobile (375) is kept as a real-device diagnostic capture.
    VIEWPORTS = {
        "desktop": {"width": 1920, "height": 1080},
        "tablet": {"width": 768, "height": 1024},
        "mobile_small": {"width": 480, "height": 860},
        "mobile": {"width": 375, "height": 812},
    }

    async def capture_viewports(
        self, page: Page, storage: LocalStorage, url: str
    ) -> Dict[str, Any]:
        logger.info("capturing_viewports", url=url)
        results = {}
        for name, dims in self.VIEWPORTS.items():
            try:
                await page.set_viewport_size(dims)  # type: ignore[arg-type]
                await page.wait_for_timeout(500)  # Settling time
                screenshot = await page.screenshot(full_page=True)

                screenshot_filename = f"capture_{name}.png"
                screenshot_path = os.path.join(
                    storage.get_asset_path(), screenshot_filename
                )
                with open(screenshot_path, "wb") as f:
                    f.write(screenshot)

                results[name] = f"assets/{screenshot_filename}"
                logger.info("viewport_captured", viewport=name)
            except Exception as e:
                logger.error("viewport_capture_failed", viewport=name, error=str(e))

        return results
