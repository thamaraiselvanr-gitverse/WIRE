"""Browser-backed verification of the stealth suite and authenticated capture.

Serves a fake ``https://app.test`` origin via request routing so web storage
and a real secure origin are available, then asserts the headless tells are
masked and every supplied credential type (cookie, header, localStorage,
sessionStorage) reaches the page. Requires a Playwright browser.
"""

import pytest


@pytest.mark.slow
@pytest.mark.asyncio
async def test_stealth_and_auth_reach_the_page():
    from wire.agents.observation.browser_session import BrowserSession

    creds = {
        "cookies": [{"name": "sid", "value": "abc", "url": "https://app.test/"}],
        "headers": {"x-api-key": "secret-token"},
        "storage": {
            "origin": "https://app.test",
            "local": {"token": "jwt123"},
            "session": {"tmp": "9"},
        },
    }

    session = BrowserSession(credentials=creds)
    await session.start()
    seen_headers: dict = {}
    try:

        async def handler(route):
            seen_headers.update(route.request.headers)
            await route.fulfill(
                status=200,
                content_type="text/html",
                body="<!doctype html><html><body><h1>app</h1></body></html>",
            )

        await session.context.route("**/*", handler)
        page = await session.context.new_page()
        await page.goto("https://app.test/", wait_until="load")

        # ── Stealth: headless tells are masked ──
        assert await page.evaluate("() => navigator.webdriver") in (None, False)
        assert await page.evaluate("() => navigator.plugins.length") > 0
        assert await page.evaluate("() => navigator.languages.length") > 0
        assert await page.evaluate("() => !!window.chrome") is True
        vendor = await page.evaluate("""() => {
                const gl = document.createElement('canvas').getContext('webgl');
                return gl ? gl.getParameter(37445) : null;
            }""")
        assert vendor == "Intel Inc."

        # ── Auth: web storage seeded before the page's own scripts ran ──
        assert await page.evaluate("() => localStorage.getItem('token')") == "jwt123"
        assert await page.evaluate("() => sessionStorage.getItem('tmp')") == "9"

        # ── Auth: header attached to the request; cookie present in context ──
        assert seen_headers.get("x-api-key") == "secret-token"
        cookies = await session.context.cookies("https://app.test/")
        assert any(c["name"] == "sid" for c in cookies)

        await page.close()
    finally:
        await session.stop()
