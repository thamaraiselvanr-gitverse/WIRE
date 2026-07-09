import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sse_starlette.sse import EventSourceResponse

from .auth import get_current_user
from .database import get_db
from .models import Project, User

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ReconstructionRequest(BaseModel):
    url: str


class BrandRequest(BaseModel):
    # Map of design-token color roles -> color values, e.g.
    # {"primary": "#0055ff", "background": "#ffffff"}.
    colors: Dict[str, Any]


class SubstituteRequest(BaseModel):
    # Map of field_id -> submitted value dict, e.g.
    # {"headline": {"type": "text", "value": "Hi"},
    #  "hero_img": {"type": "image", "value": "<b64>",
    #               "original_filename": "a.png", "content_type": "image/png"}}
    field_values: Dict[str, Any]


# In-memory queue for streaming log events to clients
log_event_queues: List["asyncio.Queue[Any]"] = []


def _run_id_for_url(url: str) -> str:
    """Mirror LocalStorage.initialize_for_url's legacy domain naming.

    Only used as a fallback for projects created before ``Project.run_id``
    existed; new projects get an isolated ``project_<id>`` directory.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    if not domain:
        import os as _os

        domain = _os.path.basename(parsed.path) or "local"
        domain, _ = _os.path.splitext(domain)
        if not domain:
            domain = "local"
    return domain.replace(":", "_")


def _project_run_id(project: Project) -> str:
    """The project's isolated run directory, or the legacy domain fallback."""
    if project.run_id:
        return str(project.run_id)
    return _run_id_for_url(str(project.url))


@router.post("")
async def start_reconstruction(
    req: ReconstructionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from wire.api.metrics import counter

    counter("reconstructions_requested_total").inc()

    # Rate limit the expensive reconstruction endpoint per user.
    from wire.api.rate_limit import reconstruction_limiter

    reconstruction_limiter.check(f"user:{current_user.id}")

    # SSRF guard at the trust boundary: reject internal/private/loopback targets
    # before the engine ever fetches or navigates to the URL.
    from wire.utils.url_guard import is_public_http_url

    if not is_public_http_url(req.url):
        raise HTTPException(
            status_code=400,
            detail="URL must be a public http(s) address "
            "(internal/private/loopback targets are not allowed).",
        )

    # Per-user daily quota (abuse control on top of the per-minute rate limit).
    from wire.api.quota import daily_reconstruction_quota

    quota = daily_reconstruction_quota()
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    used = await db.scalar(
        select(func.count())
        .select_from(Project)
        .where(Project.owner_id == current_user.id, Project.created_at >= cutoff)
    )
    if used is not None and used >= quota:
        raise HTTPException(
            status_code=429,
            detail=f"Daily reconstruction quota ({quota}) reached. Try again later.",
        )

    # Create the project and enqueue a durable job. A separate worker
    # (python -m wire.worker) drains the queue, so the work survives an API
    # restart and is retried on failure instead of being a fire-and-forget task.
    from wire.api.job_queue import enqueue

    project = Project(url=req.url, owner_id=current_user.id, status="pending")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    # Isolate this run's artifacts per project — never key output by the
    # target domain, or two users cloning the same site would share a dir.
    project.run_id = f"project_{project.id}"  # type: ignore[assignment]
    await db.commit()
    await enqueue(db, int(project.id), req.url)

    return {"message": "Reconstruction queued", "project_id": project.id}


# response_model=None: return SQLAlchemy ORM rows directly via jsonable_encoder;
# the -> Any hint must not be treated by FastAPI as a serialization model.
@router.get("", response_model=None)
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    result = await db.execute(
        select(Project)
        .where(Project.owner_id == current_user.id)
        .order_by(Project.created_at.desc())
    )
    return result.scalars().all()


@router.post("/{project_id}/brand")
async def apply_brand(
    project_id: int,
    req: BrandRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """Apply a brand palette onto a completed reconstruction and recompile.

    Restyles the stored CIDS layout with the supplied colors (preserving
    structure) and regenerates output_editable.html / React / Vue so the live
    preview reflects the new brand.
    """
    result = await db.execute(
        select(Project).where(
            (Project.id == project_id) & (Project.owner_id == current_user.id)
        )
    )
    project = result.scalars().first()
    if not project:
        raise HTTPException(
            status_code=404, detail="Project not found or access denied"
        )

    from wire.orchestrator.execution_router import ExecutionRouter

    run_id = _project_run_id(project)
    router_engine = ExecutionRouter()
    try:
        summary = router_engine.apply_brand(run_id, {"colors": req.colors})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return summary


@router.post("/{project_id}/substitute")
async def substitute_content(
    project_id: int,
    req: SubstituteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Submit user content (text/image/video/audio/document) for a run.

    Validates the submission against the run's form schema, ingests uploaded
    media/documents, maps substitutions, and generates the transformation
    prompt. Returns the SubmissionResult (validation report + prompt).
    """
    result = await db.execute(
        select(Project).where(
            (Project.id == project_id) & (Project.owner_id == current_user.id)
        )
    )
    project = result.scalars().first()
    if not project:
        raise HTTPException(
            status_code=404, detail="Project not found or access denied"
        )

    from pydantic import ValidationError

    from wire.orchestrator.execution_router import ExecutionRouter
    from wire.schema.submission_schema import SubmissionPayload

    run_id = _project_run_id(project)
    try:
        payload = SubmissionPayload(run_id=run_id, field_values=req.field_values)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"Invalid submission payload: {e}")

    router_engine = ExecutionRouter()
    try:
        submission_result = router_engine.generate_transformation_prompt(
            run_id, payload
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return submission_result.model_dump()


async def get_current_user_file(
    request: Request, db: AsyncSession, project_id: int
) -> Any:
    """Authenticate a file request via header session token or scoped token.

    Query-string tokens must be short-lived ``files``-scoped tokens bound to
    this exact project (minted by ``/file-token``). Session JWTs are only
    accepted from the Authorization header — a session token in a URL leaks
    into logs, referrers, and any untrusted content that can read its own
    location.
    """
    from jose import JWTError, jwt

    from wire.api.auth import ALGORITHM, SECRET_KEY, decode_scoped_token
    from wire.api.models import User

    username = None

    # 1. Authorization header carries the normal session token.
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            payload = jwt.decode(
                auth_header.split(" ")[1], SECRET_KEY, algorithms=[ALGORITHM]
            )
            username = payload.get("sub")
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")

    # 2. Query parameter (img/iframe src): scoped file token only.
    if username is None:
        token = request.query_params.get("token")
        if not token:
            raise HTTPException(status_code=401, detail="Authentication token missing")
        payload = decode_scoped_token(token, expected_scope="files")
        if payload.get("project_id") != project_id:
            raise HTTPException(
                status_code=401, detail="Token not valid for this project"
            )
        username = payload["sub"]

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/{project_id}/file-token")
async def issue_file_token(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Mint a short-lived token for embedding this project's files in
    ``<img>``/``<iframe>`` src URLs (which can't send an Authorization
    header). Bound to the project and the ``files`` scope."""
    from wire.api.auth import SCOPED_TOKEN_EXPIRE_MINUTES, create_scoped_token

    result = await db.execute(
        select(Project).where(
            (Project.id == project_id) & (Project.owner_id == current_user.id)
        )
    )
    if not result.scalars().first():
        raise HTTPException(
            status_code=404, detail="Project not found or access denied"
        )
    token = create_scoped_token(
        str(current_user.username), scope="files", project_id=project_id
    )
    return {"file_token": token, "expires_in": SCOPED_TOKEN_EXPIRE_MINUTES * 60}


@router.get("/{project_id}/files/{filename:path}")
async def get_project_file(
    project_id: int, filename: str, request: Request, db: AsyncSession = Depends(get_db)
) -> Any:
    import os

    from fastapi.responses import FileResponse

    # Authenticate via header session token or project-bound scoped token.
    current_user = await get_current_user_file(request, db, project_id)

    # 1. Verify project exists and belongs to current user
    result = await db.execute(
        select(Project).where(
            (Project.id == project_id) & (Project.owner_id == current_user.id)
        )
    )
    project = result.scalars().first()
    if not project:
        raise HTTPException(
            status_code=404, detail="Project not found or access denied"
        )

    # 2. Resolve the run directory using the same naming as LocalStorage
    #    (strips "www.", maps ":" to "_") so www.* sites are found correctly.
    host = _project_run_id(project)

    # 3. Resolve path cleanly to prevent directory traversal
    if "assets/" in filename or "assets\\" in filename:
        asset_name = os.path.basename(filename)
        file_path = os.path.join("output", host, "assets", asset_name)
    else:
        safe_name = os.path.basename(filename)
        file_path = os.path.join("output", host, safe_name)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    response = FileResponse(file_path)
    # Reconstructed pages are UNTRUSTED third-party content (the raw clone
    # keeps the original site's scripts). CSP `sandbox` makes the browser
    # render them script-less in an opaque origin, so cloned JS can never
    # run against the API origin or read the embedding URL's token.
    if file_path.lower().endswith((".html", ".htm", ".svg", ".xml")):
        response.headers["Content-Security-Policy"] = "sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/telemetry")
async def stream_telemetry(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Server-Sent Events (SSE) telemetry feed for the frontend.

    Requires authentication: pipeline logs reveal what is being reconstructed
    and must not be readable by anonymous clients. EventSource can't send an
    Authorization header, so a short-lived ``telemetry``-scoped token (from
    ``/api/auth/stream-token``) is accepted via ``?token=``; session JWTs in
    the query string are rejected. The queue is bounded so a slow consumer
    drops events rather than growing memory without limit.
    """
    from wire.api.auth import decode_scoped_token
    from wire.api.auth import get_current_user as _session_user

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        await _session_user(token=auth_header.split(" ")[1], db=db)
    else:
        token = request.query_params.get("token")
        if not token:
            raise HTTPException(status_code=401, detail="Authentication token missing")
        decode_scoped_token(token, expected_scope="telemetry")

    queue: "asyncio.Queue[Any]" = asyncio.Queue(maxsize=500)
    log_event_queues.append(queue)

    async def event_generator() -> AsyncGenerator[Dict[str, Any], None]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                data = await queue.get()
                yield {"data": data}
        finally:
            log_event_queues.remove(queue)

    return EventSourceResponse(event_generator())
