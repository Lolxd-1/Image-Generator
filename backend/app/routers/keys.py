"""Key-pool routes: list, add (live-validated), rename, enable/disable, test, delete."""
import uuid
from datetime import datetime, timezone

import anyio
from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.crypto import decrypt
from app.db import get_db
from app.engine import keypool, pacer
from app.engine.gemini import VISION_MODEL, build_client, is_auth_error, is_rate_limit
from app.engine.gemini import key_hash as gemini_key_hash
from app.errors import AppError
from app.models import ApiKey, PaceState, User
from app.schemas import ApiKeyIn, ApiKeyOut, ApiKeyPatch

router = APIRouter(prefix="/auth/keys", tags=["keys"])


def _validate_live(key: str) -> None:
    # Same live-validation call as auth.py's legacy put_gemini_key: a tiny real
    # request is the only way to know a key actually works before it is stored.
    try:
        client = build_client(key)
        client.models.generate_content(model=VISION_MODEL, contents="ping")
    except Exception as exc:  # noqa: BLE001 - genai raises plain Exception subtypes
        msg = str(exc)
        if is_auth_error(msg):
            raise AppError("auth_failure", "Gemini rejected this API key.", status=400)
        if is_rate_limit(msg):
            raise AppError("rate_limited", "Gemini is rate-limiting validation calls; try again shortly.", status=429)
        # Never include the raw exception text in the response - it can echo key material.
        raise AppError("validation_failed", "Could not validate the Gemini key.", status=400)


async def _key_out(db: AsyncSession, key: ApiKey) -> ApiKeyOut:
    pace = await db.get(PaceState, key.key_hash)
    if pace is None:
        delay_s = pacer.RATE_START_DELAY
        next_allowed_at = None
        busy = False
    else:
        delay_s = pace.delay_s
        next_allowed_at = pace.next_allowed_at
        busy = pace.leased_until is not None and pace.leased_until > datetime.now(timezone.utc)
    out = ApiKeyOut.model_validate(key)
    out.delay_s = delay_s
    out.next_allowed_at = next_allowed_at
    out.busy = busy
    return out


async def _get_key_or_404(db: AsyncSession, user_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey:
    key_row = await db.get(ApiKey, key_id)
    if key_row is None or key_row.user_id != user_id:
        raise AppError("not_found", "Key not found.", status=404)
    return key_row


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[ApiKeyOut]:
    rows = (
        await db.execute(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at))
    ).scalars().all()
    return [await _key_out(db, row) for row in rows]


@router.post("", response_model=ApiKeyOut, status_code=201)
async def create_key(
    payload: ApiKeyIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> ApiKeyOut:
    key = payload.key.strip()
    if not key:
        raise AppError("validation_failed", "Key is empty.", status=400)

    h = gemini_key_hash(key)
    existing = (
        await db.execute(select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.key_hash == h))
    ).scalars().first()
    if existing is not None:
        raise AppError("conflict", "That key is already in the pool.", status=409)

    await anyio.to_thread.run_sync(_validate_live, key)

    if payload.label is not None:
        label = payload.label.strip()
    else:
        n = await db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user.id))
        label = f"Key {n + 1}"

    key_row = await keypool.add_key(db, user.id, key, label)
    return await _key_out(db, key_row)


@router.patch("/{key_id}", response_model=ApiKeyOut)
async def patch_key(
    key_id: uuid.UUID,
    payload: ApiKeyPatch,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyOut:
    key_row = await _get_key_or_404(db, user.id, key_id)
    fields = payload.model_dump(exclude_unset=True)
    if "label" in fields:
        key_row.label = fields["label"]
    if "enabled" in fields:
        key_row.enabled = fields["enabled"]
        if fields["enabled"]:
            key_row.disabled_reason = None
            await db.execute(
                update(PaceState).where(PaceState.api_key_hash == key_row.key_hash).values(leased_until=None)
            )
    await db.commit()
    await db.refresh(key_row)
    return await _key_out(db, key_row)


@router.delete("/{key_id}", status_code=204)
async def remove_key(
    key_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> Response:
    key_row = await _get_key_or_404(db, user.id, key_id)
    await keypool.delete_key(db, key_row)
    return Response(status_code=204)


@router.post("/{key_id}/test", response_model=ApiKeyOut)
async def test_key(
    key_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> ApiKeyOut:
    key_row = await _get_key_or_404(db, user.id, key_id)
    plain = decrypt(key_row.key_enc)
    try:
        await anyio.to_thread.run_sync(_validate_live, plain)
    except AppError as exc:
        if exc.code == "auth_failure":
            await keypool.disable(db, key_row.key_hash, "Rejected by Gemini during test")
        raise

    key_row.enabled = True
    key_row.disabled_reason = None
    await db.commit()
    await db.refresh(key_row)
    return await _key_out(db, key_row)
