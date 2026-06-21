import structlog
from playwright.async_api import Page

logger = structlog.get_logger(__name__)


class InteractionFuzzer:
    """
    Discovers all interactive elements on a page — clickable, hoverable,
    scrollable — and enumerates their states.
    """

    INTERACTIVE_SELECTORS = [
        "a[href]",
        "button",
        "[onclick]",
        "[role='button']",
        "input[type='submit']",
        ".dropdown-toggle",
        "[data-bs-toggle]",
        "[data-toggle]",
        ".nav-link",
        ".accordion-button",
    ]

    HOVERABLE_SELECTORS = [
        "a",
        "button",
        ".nav-link",
        ".card",
        "[class*='hover']",
    ]

    async def discover_elements(self, page: Page) -> dict:
        logger.info("fuzzing_interactive_elements")
        results = {
            "clickable": [],
            "hoverable": [],
            "scrollable": [],
            "total_interactive": 0,
        }

        # Discover clickable elements
        for selector in self.INTERACTIVE_SELECTORS:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    tag = await el.evaluate("el => el.tagName")
                    text = (await el.inner_text()).strip()[:80] if await el.is_visible() else ""
                    bbox = await el.bounding_box()
                    results["clickable"].append({
                        "selector": selector,
                        "tag": tag,
                        "text": text,
                        "bbox": bbox,
                    })
            except Exception:
                pass

        # Discover hoverable elements
        for selector in self.HOVERABLE_SELECTORS:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    if await el.is_visible():
                        bbox = await el.bounding_box()
                        if bbox:
                            results["hoverable"].append({
                                "selector": selector,
                                "bbox": bbox,
                            })
            except Exception:
                pass

        # Detect scrollable containers
        scroll_containers = await page.evaluate("""
            () => {
                const scrollable = [];
                document.querySelectorAll('*').forEach(el => {
                    if (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 50 && rect.height > 50) {
                            scrollable.push({
                                tag: el.tagName,
                                id: el.id || null,
                                className: el.className || null,
                                scrollHeight: el.scrollHeight,
                                clientHeight: el.clientHeight,
                            });
                        }
                    }
                });
                return scrollable.slice(0, 50);
            }
        """)
        results["scrollable"] = scroll_containers

        results["total_interactive"] = (
            len(results["clickable"]) + len(results["hoverable"]) + len(results["scrollable"])
        )
        logger.info(
            "fuzzing_complete",
            clickable=len(results["clickable"]),
            hoverable=len(results["hoverable"]),
            scrollable=len(results["scrollable"]),
        )
        return results
