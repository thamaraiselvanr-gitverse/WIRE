import asyncio
from typing import Any, AsyncGenerator, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
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
    """Mirror LocalStorage.initialize_for_url's run-directory naming."""
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


@router.post("")
async def start_reconstruction(
    req: ReconstructionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    # SSRF guard at the trust boundary: reject internal/private/loopback targets
    # before the engine ever fetches or navigates to the URL.
    from wire.utils.url_guard import is_public_http_url

    if not is_public_http_url(req.url):
        raise HTTPException(
            status_code=400,
            detail="URL must be a public http(s) address "
            "(internal/private/loopback targets are not allowed).",
        )

    # Create project record
    project = Project(url=req.url, owner_id=current_user.id, status="running")
    db.add(project)
    await db.commit()
    await db.refresh(project)

    # In a real background setup we'd dispatch to Celery/Redis queue.
    # For now we'll simulate a start.
    asyncio.create_task(run_background_pipeline(int(project.id), req.url))

    return {"message": "Reconstruction started", "project_id": project.id}


async def run_background_pipeline(project_id: int, url: str) -> None:
    # This acts as the bridge layer calling the wire.orchestrator
    try:
        from wire.api.database import AsyncSessionLocal
        from wire.orchestrator.execution_router import ExecutionRouter

        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if not project:
                return

            router = ExecutionRouter()
            fidelity = await router.execute_pipeline(url)

            project.status = "completed"
            project.fidelity_score = fidelity
            await db.commit()
    except Exception:
        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if project:
                project.status = "failed"
                await db.commit()


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

    run_id = _run_id_for_url(str(project.url))
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

    run_id = _run_id_for_url(str(project.url))
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


async def get_current_user_file(request: Request, db: AsyncSession) -> Any:
    from jose import JWTError, jwt

    from wire.api.auth import ALGORITHM, SECRET_KEY
    from wire.api.models import User

    # 1. Try Authorization header
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

    # 2. Try query parameter (fallback for standard img src / iframe src requests)
    if not token:
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="Authentication token missing")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/{project_id}/files/{filename:path}")
async def get_project_file(
    project_id: int, filename: str, request: Request, db: AsyncSession = Depends(get_db)
) -> Any:
    import os

    from fastapi.responses import FileResponse

    # Authenticate via header or query token
    current_user = await get_current_user_file(request, db)

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
    host = _run_id_for_url(str(project.url))

    # 3. Resolve path cleanly to prevent directory traversal
    if "assets/" in filename or "assets\\" in filename:
        asset_name = os.path.basename(filename)
        file_path = os.path.join("output", host, "assets", asset_name)
    else:
        safe_name = os.path.basename(filename)
        file_path = os.path.join("output", host, safe_name)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    return FileResponse(file_path)


@router.get("/telemetry")
async def stream_telemetry(request: Request) -> Any:
    """Server-Sent Events (SSE) telemetry feed for the frontend"""
    queue: "asyncio.Queue[Any]" = asyncio.Queue()
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
