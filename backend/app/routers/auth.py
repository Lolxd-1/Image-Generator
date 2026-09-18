"""Auth routes: login, logout, current-user info, and Gemini key management."""
from datetime import datetime, timezone

import anyio
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import throttle
from app.auth import (
    DUMMY_PASSWORD_HASH,
    current_user,
    login_user,
    logout_user,
    verify_password,
)
from app.db import get_db
from app.engine import keypool
from app.engine.gemini import key_hash as gemini_key_hash
from app.errors import AppError
from app.models import ApiKey, User
from app.routers.keys import _validate_live
from app.schemas import GeminiKeyIn, GeminiKeyOut, LoginIn, MeOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


# SPEC.md §6 shows POST /api/auth/login -> {user}, distinct from the richer
# {user, has_gemini_key, gemini_key_hint} shape GET /me returns. schemas.py
# has no dedicated model for the narrower login response, and routers may
# only add response models to their own module, so it's defined here.
class LoginOut(BaseModel):
    user: UserOut


async def _me_out(db: AsyncSession, user: User) -> MeOut:
    key_count = await db.scalar(
        select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user.id)
    )
    enabled_key_count = await db.scalar(
        select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user.id, ApiKey.enabled.is_(True))
    )
    oldest_enabled = (
        await db.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user.id, ApiKey.enabled.is_(True))
            .order_by(ApiKey.created_at)
            .limit(1)
        )
    ).scalars().first()
    return MeOut(
        user=UserOut.model_validate(user),
        has_gemini_key=enabled_key_count > 0,
        gemini_key_hint=oldest_enabled.key_hint if oldest_enabled else None,
        key_count=key_count,
        enabled_key_count=enabled_key_count,
    )


@router.post("/login", response_model=LoginOut)
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginOut:
    # This endpoint is the only gate on a public URL, so failed attempts are
    # throttled per (client IP + username). See app/throttle.py.
    bucket = throttle.client_key(request, payload.username)
    wait = await throttle.check(bucket)
    if wait > 0:
        raise AppError(
            "rate_limited",
            "Too many failed sign-in attempts. Try again in "
            f"{int(wait) // 60 + 1} minute(s).",
            status=429,
            detail={"retry_after_ms": int(wait * 1000)},
        )

    user = await db.scalar(select(User).where(User.username == payload.username))
    # Always run a password verification, even when the username is unknown, so
    # response timing does not reveal which usernames exist.
    valid = verify_password(
        payload.password,
        user.password_hash if user is not None else DUMMY_PASSWORD_HASH,
    )
    if user is None or not valid:
        await throttle.record_failure(bucket)
        raise AppError("unauthorized", "Invalid username or password.", status=401)

    await throttle.clear(bucket)
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    login_user(response, user)
    return LoginOut(user=UserOut.model_validate(user))


@router.post("/logout", status_code=204)
async def logout(response: Response, user: User = Depends(current_user)) -> Response:
    logout_user(response)
    return Response(status_code=204)


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> MeOut:
    return await _me_out(db, user)


@router.put("/gemini-key", response_model=GeminiKeyOut)
async def put_gemini_key(
    payload: GeminiKeyIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> GeminiKeyOut:
    key = payload.key.strip()

    # Validate with a real, tiny live call before persisting anything —
    # never trust a key we haven't exercised against the API.
    await anyio.to_thread.run_sync(_validate_live, key)

    try:
        key_row = await keypool.add_key(db, user.id, key, "Primary")
    except AppError as exc:
        if exc.code != "conflict":
            raise
        # The key is already in the pool from an earlier call — not an error
        # for this legacy endpoint, which only promises "a key is on file".
        h = gemini_key_hash(key)
        key_row = (
            await db.execute(select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.key_hash == h))
        ).scalars().first()
    return GeminiKeyOut(has_gemini_key=True, gemini_key_hint=key_row.key_hint)


@router.delete("/gemini-key", status_code=204)
async def delete_gemini_key(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> Response:
    rows = (await db.execute(select(ApiKey).where(ApiKey.user_id == user.id))).scalars().all()
    for row in rows:
        await keypool.delete_key(db, row)
    user.gemini_key_enc = None
    user.gemini_key_hint = None
    await db.commit()
    return Response(status_code=204)
