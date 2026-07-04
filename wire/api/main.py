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

app.include_router(auth_router)
app.include_router(projects_router)


@app.get("/api/status")
async def get_status() -> Dict[str, Any]:
    return {"status": "operational", "version": "0.2.0-platform"}


@app.get("/api/metrics")
async def metrics() -> PlainTextResponse:
    """Prometheus scrape endpoint (per-process counters)."""
    return PlainTextResponse(render_prometheus())
