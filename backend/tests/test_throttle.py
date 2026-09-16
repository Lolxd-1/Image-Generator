"""Tests for app.throttle: failed-login rate limiting, no DB/Redis involved.

pytest-asyncio isn't in requirements.txt, so these drive the async functions
directly with asyncio.run() rather than adding a test-only dependency. Each
test uses its own unique key so the module-level `_buckets` dict from one test
never leaks into another.
"""
import asyncio
import uuid

from app import throttle


def _key():
    return f"test-{uuid.uuid4()}"


def test_fresh_key_is_allowed():
    key = _key()
    wait = asyncio.run(throttle.check(key))
    assert wait == 0.0


def test_max_failures_produces_a_lockout():
    key = _key()

    async def scenario():
        for _ in range(throttle.MAX_FAILURES):
            await throttle.record_failure(key)
        return await throttle.check(key)

    wait = asyncio.run(scenario())
    assert wait > 0.0


def test_fewer_than_max_failures_still_allowed():
    key = _key()

    async def scenario():
        for _ in range(throttle.MAX_FAILURES - 1):
            await throttle.record_failure(key)
        return await throttle.check(key)

    wait = asyncio.run(scenario())
    assert wait == 0.0


def test_clear_releases_the_lockout():
    key = _key()

    async def scenario():
        for _ in range(throttle.MAX_FAILURES):
            await throttle.record_failure(key)
        locked_wait = await throttle.check(key)
        await throttle.clear(key)
        cleared_wait = await throttle.check(key)
        return locked_wait, cleared_wait

    locked_wait, cleared_wait = asyncio.run(scenario())
    assert locked_wait > 0.0
    assert cleared_wait == 0.0


def test_two_different_keys_are_independent():
    attacked_key = _key()
    innocent_key = _key()

    async def scenario():
        for _ in range(throttle.MAX_FAILURES):
            await throttle.record_failure(attacked_key)
        attacked_wait = await throttle.check(attacked_key)
        innocent_wait = await throttle.check(innocent_key)
        return attacked_wait, innocent_wait

    attacked_wait, innocent_wait = asyncio.run(scenario())
    assert attacked_wait > 0.0
    assert innocent_wait == 0.0


def test_client_key_combines_ip_and_username():
    class _Client:
        host = "1.2.3.4"

    class _Request:
        client = _Client()
        headers = {}

    key1 = throttle.client_key(_Request(), "Omkar")
    key2 = throttle.client_key(_Request(), "omkar")
    assert key1 == key2  # username is case-folded
    assert "1.2.3.4" in key1


def test_client_key_honours_forwarded_for_header():
    class _Client:
        host = "10.0.0.1"  # e.g. an internal proxy address

    class _Request:
        client = _Client()
        headers = {"x-forwarded-for": "9.9.9.9, 10.0.0.1"}

    key = throttle.client_key(_Request(), "user")
    assert "9.9.9.9" in key
    assert "10.0.0.1" not in key
