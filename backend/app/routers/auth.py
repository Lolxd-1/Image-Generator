"""Auth routes: login, logout, current-user info, and Gemini key management."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import crypto, throttle
from app.auth import (
    DUMMY_PASSWORD_HASH,
    current_user,
    login_user,
    logout_user,
    verify_password,
)
from app.db import get_db
from app.engine.gemini import VISION_MODEL, build_client, is_auth_error, is_rate_limit
from app.errors import AppError
from app.models import User
from app.schemas import GeminiKeyIn, GeminiKeyOut, LoginIn, MeOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


# SPEC.md §6 shows POST /api/auth/login -> {user}, distinct from the richer
# {user, has_gemini_key, gemini_key_hint} shape GET /me returns. schemas.py
# has no dedicated model for the narrower login response, and routers may
# only add response models to their own module, so it's defined here.
class LoginOut(BaseModel):
    user: UserOut


def _me_out(user: User) -> MeOut:
    return MeOut(
        user=UserOut.model_validate(user),
        has_gemini_key=bool(user.gemini_key_enc),
        gemini_key_hint=user.gemini_key_hint,
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
async def me(user: User = Depends(current_user)) -> MeOut:
    return _me_out(user)


@router.put("/gemini-key", response_model=GeminiKeyOut)
async def put_gemini_key(
    payload: GeminiKeyIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> GeminiKeyOut:
    key = payload.key.strip()

    # Validate with a real, tiny live call before persisting anything —
    # never trust a key we haven't exercised against the API.
    try:
        client = build_client(key)
        client.models.generate_content(model=VISION_MODEL, contents="ping")
    except Exception as exc:  # noqa: BLE001 - genai raises plain Exception subtypes
        msg = str(exc)
        if is_auth_error(msg):
            raise AppError("auth_failure", "Gemini rejected this API key.", status=400)
        if is_rate_limit(msg):
            raise AppError("rate_limited", "Gemini is rate-limiting validation calls; try again shortly.", status=429)
        # SPEC-GAP: SPEC.md only defines the auth_failure outcome for this
        # validation call. Any other failure (network, unexpected response
        # shape, etc.) is surfaced as validation_failed rather than silently
        # storing an unverified key. The raw exception text is not included
        # in the response to avoid ever echoing key material back.
        raise AppError("validation_failed", "Could not validate the Gemini key.", status=400)

    user.gemini_key_enc = crypto.encrypt(key)
    user.gemini_key_hint = crypto.key_hint(key)
    await db.commit()
    await db.refresh(user)
    return GeminiKeyOut(has_gemini_key=True, gemini_key_hint=user.gemini_key_hint)


@router.delete("/gemini-key", status_code=204)
async def delete_gemini_key(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> Response:
    user.gemini_key_enc = None
    user.gemini_key_hint = None
    await db.commit()
    return Response(status_code=204)
