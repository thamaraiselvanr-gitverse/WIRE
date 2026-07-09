import contextlib
import os
from typing import Any, AsyncGenerator, Dict

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .auth_routes import router as auth_router
from .database import Base, engine
from .main_routes import router as projects_router
from .metrics import render_prometheus

logger = structlog.get_logger(__name__)


def _init_sentry() -> None:
    """Initialize Sentry error reporting if SENTRY_DSN is set (no-op otherwise)."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=float(
                os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.0")
            ),
            environment=os.environ.get("WIRE_ENV", "production"),
        )
        logger.info("sentry_initialized")
    except Exception as e:  # pragma: no cover - optional dependency / bad DSN
        logger.warning("sentry_init_failed", error=str(e))


_init_sentry()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="WIRE Platform API", lifespan=lifespan)

# Allowed browser origins are configurable via WIRE_CORS_ORIGINS (comma-
# separated) so production hosts can be set without a code change; defaults to
# the local Vite dev server.
_cors_origins = [
    o.strip()
    for o in os.environ.get(
        "WIRE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Any, call_next: Any) -> Any:
    """Baseline security headers + request-latency histogram on every response.

    ``setdefault`` so route-specific headers win (the file endpoint sets its
    own CSP ``sandbox`` for untrusted reconstructed pages). Framing is denied
    everywhere except served files — the dashboard legitimately embeds
    ``/files/*.html`` previews in an iframe. HSTS is opt-in via
    ``WIRE_ENABLE_HSTS`` because emitting it from a plain-HTTP deployment
    (local dev, behind-TLS-terminating-proxy misconfig) can lock browsers out.
    The SSE telemetry stream is excluded from latency (connections are
    intentionally long-lived and would swamp the histogram).
    """
    import time

    from .metrics import histogram

    start = time.perf_counter()
    response = await call_next(request)
    if "/telemetry" not in request.url.path:
        histogram("http_request_duration_seconds").observe(time.perf_counter() - start)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if "/files/" not in request.url.path:
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    if os.environ.get("WIRE_ENABLE_HSTS", "").lower() in ("1", "true", "yes"):
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


app.include_router(auth_router)
app.include_router(projects_router)


@app.get("/api/status")
async def get_status() -> Dict[str, Any]:
    return {"status": "operational", "version": "0.2.0-platform"}


@app.get("/api/metrics")
async def metrics() -> PlainTextResponse:
    """Prometheus scrape endpoint (per-process counters)."""
    return PlainTextResponse(render_prometheus())
