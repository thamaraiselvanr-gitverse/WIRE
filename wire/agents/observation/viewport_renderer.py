import structlog
import os
from playwright.async_api import Page
from wire.storage.local import LocalStorage

logger = structlog.get_logger(__name__)

class ViewportRenderer:
    VIEWPORTS = {
        "desktop": {"width": 1920, "height": 1080},
        "tablet": {"width": 768, "height": 1024},
        "mobile": {"width": 375, "height": 812}
    }

    async def capture_viewports(self, page: Page, storage: LocalStorage, url: str) -> dict:
        logger.info("capturing_viewports", url=url)
        results = {}
        for name, dims in self.VIEWPORTS.items():
            try:
                await page.set_viewport_size(dims)
                await page.wait_for_timeout(500) # Settling time
                screenshot = await page.screenshot(full_page=True)
                
                screenshot_filename = f"capture_{name}.png"
                screenshot_path = os.path.join(storage.get_asset_path(), screenshot_filename)
                with open(screenshot_path, "wb") as f:
                    f.write(screenshot)
                    
                results[name] = f"assets/{screenshot_filename}"
                logger.info(f"viewport_captured", viewport=name)
            except Exception as e:
                logger.error("viewport_capture_failed", viewport=name, error=str(e))
                
        return results
