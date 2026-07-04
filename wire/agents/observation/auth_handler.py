"""Authenticated capture for pages behind a login.

Cookie injection alone only covers cookie-session sites. Real targets also use
``localStorage``/``sessionStorage`` tokens (SPAs), bearer/API-key headers, and
HTTP Basic auth. This handler applies whichever credentials the operator
supplies and can assemble a Playwright ``storage_state`` for context creation.

Credentials are provided by the operator for pages they are authorized to
access — nothing here discovers or brute-forces anything.
"""

import json
from typing import Any, Optional

import structlog
from playwright.async_api import BrowserContext

logger = structlog.get_logger(__name__)


class AuthHandler:
    @staticmethod
    async def inject_session(
        context: BrowserContext, cookies: list[dict[str, Any]]
    ) -> None:
        """Add session cookies to the context."""
        if cookies:
            logger.info("injecting_session_cookies", count=len(cookies))
            await context.add_cookies(cookies)  # type: ignore[arg-type]

    @staticmethod
    async def inject_storage(
        context: BrowserContext,
        origin: str,
        local_storage: Optional[dict[str, Any]] = None,
        session_storage: Optional[dict[str, Any]] = None,
    ) -> None:
        """Seed ``localStorage``/``sessionStorage`` for ``origin`` before load.

        Registered as an init script so the values exist the moment the page's
        own scripts run (many SPAs read their auth token at boot).
        """
        local_storage = local_storage or {}
        session_storage = session_storage or {}
        if not local_storage and not session_storage:
            return
        logger.info(
            "injecting_web_storage",
            origin=origin,
            local_keys=len(local_storage),
            session_keys=len(session_storage),
        )
        # add_init_script runs this as a script body (not a called function).
        script = (
            "if (location.origin === %s) {"
            "const L=%s; for (const k in L) localStorage.setItem(k, L[k]);"
            "const S=%s; for (const k in S) sessionStorage.setItem(k, S[k]);"
            "}"
            % (
                json.dumps(origin),
                _js_obj(local_storage),
                _js_obj(session_storage),
            )
        )
        await context.add_init_script(script)

    @staticmethod
    async def apply_headers(context: BrowserContext, headers: dict[str, str]) -> None:
        """Attach extra HTTP headers (bearer tokens, API keys) to every request."""
        if headers:
            logger.info("applying_auth_headers", keys=sorted(headers.keys()))
            await context.set_extra_http_headers(headers)

    @staticmethod
    def basic_auth_args(username: str, password: str) -> dict[str, Any]:
        """Return ``new_context`` kwargs for HTTP Basic auth."""
        return {"http_credentials": {"username": username, "password": password}}

    @staticmethod
    def build_storage_state(
        cookies: Optional[list[dict[str, Any]]] = None,
        origins: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Assemble a Playwright ``storage_state`` dict for context creation.

        ``origins`` is a list of ``{"origin", "localStorage": [{"name","value"}]}``
        as Playwright expects. Passing this to ``new_context(storage_state=...)``
        is the most robust way to restore a full authenticated session.
        """
        return {"cookies": cookies or [], "origins": origins or []}

    @classmethod
    async def authenticate(
        cls, context: BrowserContext, credentials: Optional[dict[str, Any]] = None
    ) -> None:
        """Apply every credential type present in ``credentials``.

        Recognized keys: ``cookies`` (list), ``headers`` (dict), and ``storage``
        (``{"origin", "local", "session"}``). Missing keys are skipped, so a
        caller supplies only what the target needs.
        """
        if not credentials:
            return
        if credentials.get("cookies"):
            await cls.inject_session(context, credentials["cookies"])
        if credentials.get("headers"):
            await cls.apply_headers(context, credentials["headers"])
        storage = credentials.get("storage")
        if storage and storage.get("origin"):
            await cls.inject_storage(
                context,
                storage["origin"],
                storage.get("local"),
                storage.get("session"),
            )


def _js_obj(d: dict[str, Any]) -> str:
    """Serialize a flat str->str dict to a JS object literal, safely escaped."""
    return json.dumps({str(k): str(v) for k, v in d.items()})
