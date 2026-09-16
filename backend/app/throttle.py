"""Failed-login throttling.

This app sits on a public URL and its only gate is a hardcoded password, so an
unthrottled /auth/login is an open invitation to a credential-stuffing script.
There is no Redis on a zero-cost host, and the app runs as a single instance,
so an in-process sliding window is the right size of solution: no dependency,
no infrastructure, and it resets on restart (which is acceptable — an attacker
cannot trigger restarts).

Counts FAILED attempts only. A successful login clears the bucket, so a person
who fat-fingers a password twice and then gets it right is never penalised.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque

# A burst of 8 gives a human plenty of room; a script hits the wall immediately.
MAX_FAILURES = 8
WINDOW_SECONDS = 300.0      # failures older than this fall out of the window
LOCKOUT_SECONDS = 300.0     # how long to refuse once the window is full

_buckets: dict[str, deque[float]] = {}
_lock = asyncio.Lock()


def _prune(bucket: deque[float], now: float) -> None:
    while bucket and now - bucket[0] > WINDOW_SECONDS:
        bucket.popleft()


async def check(key: str) -> float:
    """Return 0.0 if the caller may attempt a login, else seconds to wait."""
    now = time.monotonic()
    async with _lock:
        bucket = _buckets.get(key)
        if not bucket:
            return 0.0
        _prune(bucket, now)
        if len(bucket) < MAX_FAILURES:
            return 0.0
        # Full window: refuse until the oldest failure ages out.
        wait = LOCKOUT_SECONDS - (now - bucket[-1])
        return max(wait, 0.0)


async def record_failure(key: str) -> None:
    now = time.monotonic()
    async with _lock:
        bucket = _buckets.setdefault(key, deque())
        _prune(bucket, now)
        bucket.append(now)
        # Never let a hostile caller grow memory without bound.
        while len(bucket) > MAX_FAILURES * 2:
            bucket.popleft()
        if len(_buckets) > 4096:
            _buckets.clear()


async def clear(key: str) -> None:
    async with _lock:
        _buckets.pop(key, None)


def client_key(request, username: str) -> str:
    """Bucket on client IP + username, so one attacker cannot lock out a real user.

    Throttling on username alone would let anyone deny a colleague access by
    spamming their username. Throttling on IP alone is defeated by rotating the
    username. Both together is the useful pair.
    """
    client = getattr(request, "client", None)
    ip = getattr(client, "host", None) or "unknown"
    # Honour a proxy header when present; a free host always sits behind one.
    forwarded = request.headers.get("x-forwarded-for") if hasattr(request, "headers") else None
    if forwarded:
        ip = forwarded.split(",")[0].strip() or ip
    return f"{ip}|{username.strip().lower()}"
