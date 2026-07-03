import asyncio

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
    colors: dict


# In-memory queue for streaming log events to clients
log_event_queues = []


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
):
    # Create project record
    project = Project(url=req.url, owner_id=current_user.id, status="running")
    db.add(project)
    await db.commit()
    await db.refresh(project)

    # In a real background setup we'd dispatch to Celery/Redis queue.
    # For now we'll simulate a start.
    asyncio.create_task(run_background_pipeline(project.id, req.url))

    return {"message": "Reconstruction started", "project_id": project.id}


async def run_background_pipeline(project_id: int, url: str):
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


@router.get("")
async def list_projects(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
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
):
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

    run_id = _run_id_for_url(project.url)
    router_engine = ExecutionRouter()
    try:
        summary = router_engine.apply_brand(run_id, {"colors": req.colors})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return summary


async def get_current_user_file(request: Request, db: AsyncSession):
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
):
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
    host = _run_id_for_url(project.url)

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
async def stream_telemetry(request: Request):
    """Server-Sent Events (SSE) telemetry feed for the frontend"""
    queue = asyncio.Queue()
    log_event_queues.append(queue)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                data = await queue.get()
                yield {"data": data}
        finally:
            log_event_queues.remove(queue)

    return EventSourceResponse(event_generator())
