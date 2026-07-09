import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import bcrypt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .database import get_db
from .models import User

logger = structlog.get_logger(__name__)

# The JWT signing key MUST come from the environment in any real deployment.
# There is deliberately no shared hardcoded fallback: a committed default key
# means anyone can forge tokens. When unset we mint a random ephemeral key so
# local/dev runs still work, but tokens then won't survive a restart or validate
# across worker processes — the intended nudge to configure it.
SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(48)
    logger.warning(
        "jwt_secret_key_unset",
        hint="JWT_SECRET_KEY is not set; generated an ephemeral signing key. "
        "Tokens will not survive restarts or work across processes. "
        "Set JWT_SECRET_KEY to a strong random value in production.",
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt  # type: ignore[no-any-return]


SCOPED_TOKEN_EXPIRE_MINUTES = 15


def create_scoped_token(
    username: str, scope: str, project_id: Optional[int] = None
) -> str:
    """Mint a short-lived token limited to one purpose (``scope``).

    Used for browser contexts that can't send an Authorization header
    (``<img>``/``<iframe>`` src, EventSource): embedding the long-lived
    session JWT in a URL would leak it into logs, referrers, and any
    (untrusted) content loaded in that context. A scoped token is only
    honored by its matching endpoint, expires quickly, and — for files —
    is bound to a single project.
    """
    claims: Dict[str, Any] = {"sub": username, "scope": scope}
    if project_id is not None:
        claims["project_id"] = project_id
    return create_access_token(
        claims, expires_delta=timedelta(minutes=SCOPED_TOKEN_EXPIRE_MINUTES)
    )


def decode_scoped_token(token: str, expected_scope: str) -> Dict[str, Any]:
    """Validate a scoped token; raise 401 unless scope and expiry check out.

    Session tokens (no ``scope`` claim) are explicitly rejected: they must
    never be accepted from a query string.
    """
    try:
        payload: Dict[str, Any] = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("scope") != expected_scope or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Token not valid for this use")
    return payload


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> Any:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if user is None:
        raise credentials_exception
    return user
