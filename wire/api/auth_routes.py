from datetime import timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    SCOPED_TOKEN_EXPIRE_MINUTES,
    consume_refresh_token,
    create_access_token,
    create_scoped_token,
    get_current_user,
    get_password_hash,
    mint_refresh_token,
    revoke_refresh_token,
    verify_password,
)
from .database import get_db
from .models import User
from .rate_limit import auth_limiter


def _client_key(request: Request) -> str:
    return f"ip:{request.client.host if request.client else 'unknown'}"


router = APIRouter(prefix="/api/auth", tags=["auth"])


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator("username")
    @classmethod
    def username_shape(cls, v: str) -> str:
        v = v.strip()
        if not (3 <= len(v) <= 50):
            raise ValueError("username must be 3-50 characters")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        # Length-first policy (NIST 800-63B): long enough to resist online
        # guessing, capped to keep bcrypt input bounded (it truncates at 72
        # bytes anyway).
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        if len(v) > 72:
            raise ValueError("password must be at most 72 characters")
        if v.isdigit():
            raise ValueError("password cannot be all digits")
        return v


class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/register", response_model=Token)
async def register(
    user: UserCreate, request: Request, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    auth_limiter.check(_client_key(request))
    result = await db.execute(
        select(User).where(
            (User.username == user.username) | (User.email == user.email)
        )
    )
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=400, detail="Username or email already registered"
        )

    hashed_password = get_password_hash(user.password)
    db_user = User(
        username=user.username, email=user.email, hashed_password=hashed_password
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": db_user.username}, expires_delta=access_token_expires
    )
    refresh_token = await mint_refresh_token(db, db_user)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
    }


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    auth_limiter.check(_client_key(request))
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalars().first()
    if not user or not verify_password(form_data.password, str(user.hashed_password)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    refresh_token = await mint_refresh_token(db, user)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
    }


@router.post("/refresh", response_model=Token)
async def refresh(
    req: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Exchange a refresh token for a new access + refresh pair (rotation).

    The presented token is single-use: it is revoked on consumption, so a
    replayed copy is dead after the first legitimate refresh.
    """
    auth_limiter.check(_client_key(request))
    user = await consume_refresh_token(db, req.refresh_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    new_refresh = await mint_refresh_token(db, user)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": new_refresh,
    }


@router.post("/logout")
async def logout(
    req: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Revoke a refresh token. Possession is sufficient authorization —
    revoking a token you hold is never an escalation."""
    auth_limiter.check(_client_key(request))
    revoked = await revoke_refresh_token(db, req.refresh_token)
    return {"revoked": revoked}


@router.get("/stream-token")
async def issue_stream_token(user: Any = Depends(get_current_user)) -> Dict[str, Any]:
    """Mint a short-lived ``telemetry``-scoped token for EventSource.

    EventSource can't send an Authorization header; embedding the session JWT
    in the stream URL would leak it. This token only opens the telemetry
    stream and expires quickly.
    """
    token = create_scoped_token(str(user.username), scope="telemetry")
    return {"stream_token": token, "expires_in": SCOPED_TOKEN_EXPIRE_MINUTES * 60}
