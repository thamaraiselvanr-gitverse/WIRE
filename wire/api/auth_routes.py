from datetime import timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_password_hash,
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


class Token(BaseModel):
    access_token: str
    token_type: str


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
    return {"access_token": access_token, "token_type": "bearer"}


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
    return {"access_token": access_token, "token_type": "bearer"}
