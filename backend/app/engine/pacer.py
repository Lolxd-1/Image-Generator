"""Adaptive rate control for the Gemini image API, DB-backed so state survives restarts.

Ported verbatim from main.py's ADAPTIVE RATE CONTROL block (the constants and the
grow/shrink/backoff maths were tuned against a flaky free-tier quota — do not
re-tune them). The only structural change from the original is that pacing state
now lives in the `PaceState` table (per API key) instead of in-process instance
attributes, since retries here span separate `/step` HTTP calls rather than a
single long-running thread.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PaceState

# ── ADAPTIVE RATE CONTROL (express mode) — verbatim from main.py ──────────
# Measured: express-mode image quota rejects bursts instantly and
# sustains roughly one image per ~30-60s on the free tier.
# The pace self-tunes: it grows on every 429, shrinks on success.
RATE_START_DELAY = 30.0    # seconds between calls at startup
RATE_MIN_DELAY = 8.0       # never go faster than this
RATE_MAX_DELAY = 120.0     # never go slower than this
RATE_GROW = 1.5            # multiply pace by this on a 429
RATE_SHRINK = 0.92         # multiply pace by this on a success
RATE_BACKOFF_BASE = 20.0   # first 429 sleep
RATE_BACKOFF_MAX = 300.0   # cap on 429 sleep


def grow(delay: float) -> float:
    return min(delay * RATE_GROW, RATE_MAX_DELAY)


def shrink(delay: float) -> float:
    return max(delay * RATE_SHRINK, RATE_MIN_DELAY)


def backoff(attempt: int) -> float:
    return min(RATE_BACKOFF_BASE * (2 ** attempt), RATE_BACKOFF_MAX)


async def get_or_create(db: AsyncSession, api_key_hash: str) -> PaceState:
    state = await db.get(PaceState, api_key_hash)
    if state is None:
        state = PaceState(
            api_key_hash=api_key_hash,
            delay_s=RATE_START_DELAY,
            next_allowed_at=None,
            consecutive_429=0,
        )
        db.add(state)
        await db.flush()
    return state


async def on_success(db: AsyncSession, api_key_hash: str) -> float:
    """Call went through -> creep back toward a faster pace."""
    state = await get_or_create(db, api_key_hash)
    state.delay_s = shrink(state.delay_s)
    state.consecutive_429 = 0
    state.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return state.delay_s


async def on_rate_limit(db: AsyncSession, api_key_hash: str) -> float:
    """429 seen -> slow everything down, and return the seconds to wait."""
    state = await get_or_create(db, api_key_hash)
    state.delay_s = grow(state.delay_s)
    # backoff() is 0-indexed in the original (first 429 waits RATE_BACKOFF_BASE,
    # i.e. 20s). Compute from the PRE-increment count so the first 429 stays 20s
    # rather than jumping straight to 40s.
    wait = backoff(state.consecutive_429)
    state.consecutive_429 += 1
    state.next_allowed_at = datetime.now(timezone.utc) + timedelta(seconds=wait)
    state.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return wait
