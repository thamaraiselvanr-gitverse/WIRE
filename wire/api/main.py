import contextlib
import os
from typing import Any, AsyncGenerator, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth_routes import router as auth_router
from .database import Base, engine
from .main_routes import router as projects_router


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
