from playwright.async_api import BrowserContext


class StealthManager:
    @staticmethod
    async def apply_stealth(context: BrowserContext) -> None:
        # MVP Stealth: modify HTTP headers, pretend to be a standard browser
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
