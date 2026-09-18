"""Signed session-cookie auth: user seeding, login/logout, and the current_user dependency."""
import json
import uuid

from fastapi import Depends, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.errors import AppError
from app.models import User

COOKIE_NAME = "session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_serializer = URLSafeTimedSerializer(settings.SESSION_SECRET, salt="session-cookie")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain, password_hash)


# A real bcrypt hash of a fixed random string. Verifying an unknown username
# against this keeps the failure path the same cost as the success path, so
# response timing cannot be used to enumerate which usernames exist.
DUMMY_PASSWORD_HASH = _pwd_context.hash("not-a-real-password-timing-equaliser")


async def seed_users(db: AsyncSession) -> None:
    """Insert any APP_USERS entry whose username doesn't exist yet.

    Idempotent: existing users (and their password hashes) are never touched.
    """
    entries = json.loads(settings.APP_USERS)
    for entry in entries:
        username = entry["username"]
        existing = await db.scalar(select(User).where(User.username == username))
        if existing is not None:
            continue
        db.add(User(username=username, password_hash=_pwd_context.hash(entry["password"])))
    await db.commit()


def login_user(response: Response, user: User) -> None:
    """Set the signed session cookie for `user` on `response`."""
    token = _serializer.dumps(str(user.id))
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=True,
        path="/",
    )


def logout_user(response: Response) -> None:
    """Clear the session cookie on `response`."""
    response.delete_cookie(key=COOKIE_NAME, path="/")


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """FastAPI dependency: resolve the signed-in User from the session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise AppError("unauthorized", "Not signed in.", status=401)
    try:
        raw_id = _serializer.loads(token, max_age=COOKIE_MAX_AGE)
        user_id = uuid.UUID(raw_id)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        raise AppError("unauthorized", "Session is invalid or expired.", status=401)
    user = await db.get(User, user_id)
    if user is None:
        raise AppError("unauthorized", "Not signed in.", status=401)
    return user
