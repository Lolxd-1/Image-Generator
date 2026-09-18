"""Owns every decision about WHICH Gemini API key a request uses.

This module is the only place that reads or writes both `api_keys` and
`pace_state` together. `app/engine/pacer.py` owns the grow/shrink/backoff
maths per key hash and is used unchanged here: keypool decides WHICH key,
pacer decides HOW LONG that key waits.

The plaintext a function here returns (`lease`'s second tuple element,
`pick_any`'s return value) must never be logged, persisted, or put into a
response or a `JobEvent` message.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt, key_hint
from app.engine import pacer
from app.engine.gemini import key_hash as gemini_key_hash
from app.errors import AppError
from app.models import ApiKey, PaceState, User

logger = logging.getLogger(__name__)

LEASE_SECONDS = 150        # must exceed gemini.API_TIMEOUT (90s) plus storage-write headroom
MAX_LANES = 6
WAIT_CAP_MS = 60_000


@dataclass(frozen=True)
class Candidate:
    key_hash: str
    enabled: bool
    next_allowed_at: datetime | None
    leased_until: datetime | None
    last_used_at: datetime | None


def _aware(dt: datetime | None) -> datetime | None:
    """Treat a naive datetime as UTC rather than raising on comparison."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def free_at(c: Candidate) -> datetime | None:
    """The later of `next_allowed_at` and `leased_until`; `None` means no constraint."""
    a = _aware(c.next_allowed_at)
    b = _aware(c.leased_until)
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def wait_ms_until(cands: Sequence[Candidate], now: datetime) -> int | None:
    enabled = [c for c in cands if c.enabled]
    if not enabled:
        return None
    soonest: datetime | None = None
    for c in enabled:
        at = free_at(c)
        if at is None or at <= now:
            return 0
        if soonest is None or at < soonest:
            soonest = at
    assert soonest is not None
    ms = int((soonest - now).total_seconds() * 1000)
    return min(max(ms, 1), WAIT_CAP_MS)


def lane_count(enabled: int) -> int:
    return min(max(enabled, 1), MAX_LANES)


def _lease_stmt(user_id: uuid.UUID, now: datetime):
    """The single UPDATE ... RETURNING statement `lease` executes, pulled out
    so a test can compile it and assert its shape (FOR UPDATE OF pace_state
    SKIP LOCKED) without ever needing a DB."""
    candidate = (
        select(PaceState.api_key_hash)
        .join(ApiKey, ApiKey.key_hash == PaceState.api_key_hash)
        .where(
            ApiKey.user_id == user_id,
            ApiKey.enabled.is_(True),
            or_(PaceState.next_allowed_at.is_(None), PaceState.next_allowed_at <= now),
            or_(PaceState.leased_until.is_(None), PaceState.leased_until <= now),
        )
        .order_by(PaceState.next_allowed_at.asc().nullsfirst(), ApiKey.last_used_at.asc().nullsfirst())
        .with_for_update(skip_locked=True, of=PaceState)
        .limit(1)
    )
    return (
        update(PaceState)
        .where(PaceState.api_key_hash == candidate.scalar_subquery())
        .values(leased_until=now + timedelta(seconds=LEASE_SECONDS))
        .returning(PaceState.api_key_hash)
        .execution_options(synchronize_session=False)
    )


async def lease(db: AsyncSession, user_id: uuid.UUID) -> tuple[ApiKey, str] | None:
    now = datetime.now(timezone.utc)
    leased_hash = (await db.execute(_lease_stmt(user_id, now))).scalars().first()
    if leased_hash is None:
        await db.commit()
        return None

    key_row = (
        await db.execute(
            select(ApiKey).where(ApiKey.key_hash == leased_hash, ApiKey.user_id == user_id)
        )
    ).scalars().first()
    if key_row is None:
        # The ApiKey row vanished between the lease UPDATE and this SELECT
        # (a concurrent delete) - give the lease back rather than raising on
        # a None dereference below, which would otherwise leak it for
        # LEASE_SECONDS.
        await release_now(db, leased_hash)
        return None
    key_row.last_used_at = now
    await db.commit()
    return key_row, decrypt(key_row.key_enc)


async def release(db: AsyncSession, key_hash: str, delay_s: float) -> None:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(PaceState)
        .where(PaceState.api_key_hash == key_hash)
        .values(next_allowed_at=now + timedelta(seconds=delay_s), leased_until=None)
    )
    await db.commit()


async def release_now(db: AsyncSession, key_hash: str) -> None:
    await db.execute(
        update(PaceState).where(PaceState.api_key_hash == key_hash).values(leased_until=None)
    )
    await db.commit()


async def wait_ms(db: AsyncSession, user_id: uuid.UUID) -> int | None:
    # INNER join, matching `lease`'s candidate set: a key with no pace_state
    # row is never a lease candidate (add_key/migrate_legacy_keys always
    # create one), so it must not be a wait_ms candidate either - otherwise
    # it would report "free now" while lease can never actually pick it,
    # looping a lane forever.
    rows = (
        await db.execute(
            select(ApiKey, PaceState)
            .join(PaceState, PaceState.api_key_hash == ApiKey.key_hash)
            .where(ApiKey.user_id == user_id)
        )
    ).all()
    cands = [
        Candidate(
            key_hash=key.key_hash,
            enabled=key.enabled,
            next_allowed_at=pace.next_allowed_at,
            leased_until=pace.leased_until,
            last_used_at=key.last_used_at,
        )
        for key, pace in rows
    ]
    return wait_ms_until(cands, datetime.now(timezone.utc))


async def enabled_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user_id, ApiKey.enabled.is_(True))
    )
    return result.scalar_one()


async def disable(db: AsyncSession, key_hash: str, reason: str) -> None:
    await db.execute(
        update(ApiKey)
        .where(ApiKey.key_hash == key_hash)
        .values(enabled=False, disabled_reason=reason[:300])
    )
    await db.execute(
        update(PaceState).where(PaceState.api_key_hash == key_hash).values(leased_until=None)
    )
    await db.commit()


async def add_key(db: AsyncSession, user_id: uuid.UUID, plain: str, label: str) -> ApiKey:
    h = gemini_key_hash(plain)
    existing = (
        await db.execute(
            select(ApiKey).where(ApiKey.user_id == user_id, ApiKey.key_hash == h)
        )
    ).scalars().first()
    if existing is not None:
        raise AppError("conflict", "That key is already in the pool.", status=409)

    key_row = ApiKey(
        user_id=user_id,
        label=label,
        key_enc=encrypt(plain),
        key_hint=key_hint(plain),
        key_hash=h,
    )
    db.add(key_row)
    try:
        # get_or_create's own flush() can also hit the race below (the same
        # key_hash means the same pace_state PK too), so it must be inside
        # this try along with the commit.
        await pacer.get_or_create(db, h)
        await db.commit()
    except IntegrityError:
        # A concurrent add of the same key raced past the check above and
        # hit uq_api_keys_user_key - report it the same way as the check.
        await db.rollback()
        raise AppError("conflict", "That key is already in the pool.", status=409)
    return key_row


async def delete_key(db: AsyncSession, key: ApiKey) -> None:
    h = key.key_hash
    await db.delete(key)
    await db.flush()
    remaining = (
        await db.execute(select(func.count()).select_from(ApiKey).where(ApiKey.key_hash == h))
    ).scalar_one()
    if remaining == 0:
        pace = await db.get(PaceState, h)
        if pace is not None:
            await db.delete(pace)
    await db.commit()


async def pick_any(db: AsyncSession, user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    key_row = (
        await db.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user_id, ApiKey.enabled.is_(True))
            .order_by(ApiKey.last_used_at.asc().nullsfirst())
            .limit(1)
        )
    ).scalars().first()
    if key_row is None:
        raise AppError("no_api_key", "No Gemini API key is on file. Add one in Settings.", status=400)
    key_row.last_used_at = now
    await db.commit()
    return decrypt(key_row.key_enc)


async def migrate_legacy_keys(db: AsyncSession) -> int:
    rows = (await db.execute(select(User).where(User.gemini_key_enc.is_not(None)))).scalars().all()
    inserted = 0
    for user in rows:
        try:
            plain = decrypt(user.gemini_key_enc)
        except Exception:
            logger.warning("migrate_legacy_keys: could not decrypt legacy key for user_id=%s", user.id)
            continue
        h = gemini_key_hash(plain)
        existing = (
            await db.execute(
                select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.key_hash == h)
            )
        ).scalars().first()
        if existing is not None:
            continue
        db.add(
            ApiKey(
                user_id=user.id,
                label="Primary",
                key_enc=encrypt(plain),
                key_hint=key_hint(plain),
                key_hash=h,
            )
        )
        await pacer.get_or_create(db, h)
        inserted += 1
    await db.commit()
    return inserted
