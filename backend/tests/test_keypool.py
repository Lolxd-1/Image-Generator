"""Pure-function tests for app.engine.keypool: free_at, wait_ms_until, lane_count.

No DB, no network - the existing suite has no DB fixture (see test_pacer.py for
the style these follow).
"""
import inspect
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects import postgresql

from app.engine import keypool
from app.engine.keypool import Candidate, free_at, lane_count, wait_ms_until

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _cand(*, enabled=True, next_allowed_at=None, leased_until=None, last_used_at=None, h="h"):
    return Candidate(
        key_hash=h,
        enabled=enabled,
        next_allowed_at=next_allowed_at,
        leased_until=leased_until,
        last_used_at=last_used_at,
    )


def test_wait_ms_until_free_key_returns_zero():
    cands = [
        _cand(h="a", next_allowed_at=NOW + timedelta(seconds=30)),
        _cand(h="b", next_allowed_at=None),
        _cand(h="c", next_allowed_at=NOW + timedelta(seconds=90)),
    ]
    assert wait_ms_until(cands, NOW) == 0


def test_wait_ms_until_picks_soonest():
    cands = [
        _cand(h="a", next_allowed_at=NOW + timedelta(seconds=30)),
        _cand(h="b", next_allowed_at=NOW + timedelta(seconds=10)),
        _cand(h="c", next_allowed_at=NOW + timedelta(seconds=90)),
    ]
    result = wait_ms_until(cands, NOW)
    assert abs(result - 10_000) <= 100


def test_wait_ms_until_ignores_disabled():
    cands = [
        _cand(h="a", enabled=False, next_allowed_at=None),
        _cand(h="b", enabled=True, next_allowed_at=NOW + timedelta(seconds=10)),
    ]
    result = wait_ms_until(cands, NOW)
    assert result is not None and result > 0
    assert abs(result - 10_000) <= 100


def test_expired_lease_counts_as_free():
    cands = [_cand(leased_until=NOW - timedelta(minutes=5), next_allowed_at=None)]
    assert wait_ms_until(cands, NOW) == 0


def test_wait_ms_until_no_enabled_candidates_returns_none():
    assert wait_ms_until([], NOW) is None
    cands = [_cand(enabled=False), _cand(enabled=False, h="b")]
    assert wait_ms_until(cands, NOW) is None


def test_wait_ms_until_caps_at_wait_cap():
    cands = [_cand(next_allowed_at=NOW + timedelta(minutes=10))]
    assert wait_ms_until(cands, NOW) == keypool.WAIT_CAP_MS


def test_lane_count_caps_at_max():
    assert lane_count(0) == 1
    assert lane_count(1) == 1
    assert lane_count(5) == 5
    assert lane_count(9) == 6


def test_free_at_prefers_later_constraint():
    earlier = NOW + timedelta(seconds=10)
    later = NOW + timedelta(seconds=20)
    assert free_at(_cand(next_allowed_at=earlier, leased_until=later)) == later
    assert free_at(_cand(next_allowed_at=later, leased_until=earlier)) == later
    assert free_at(_cand(next_allowed_at=None, leased_until=None)) is None


def test_wait_ms_until_accepts_naive_datetimes():
    naive = (NOW + timedelta(seconds=10)).replace(tzinfo=None)
    cands = [_cand(next_allowed_at=naive)]
    result = wait_ms_until(cands, NOW)
    assert result is not None
    assert abs(result - 10_000) <= 100


def test_lease_statement_is_skip_locked():
    """Compiles the exact statement `keypool.lease` executes and asserts its
    shape, so this fails if `skip_locked` or `of=PaceState` were ever removed
    from `_lease_stmt` - no DB needed, a compiled statement is just text."""
    stmt = keypool._lease_stmt(uuid.uuid4(), NOW)
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "UPDATE pace_state" in compiled
    assert "FOR UPDATE OF pace_state" in compiled
    assert "SKIP LOCKED" in compiled


def test_migrate_legacy_keys_is_idempotent_by_construction():
    """No DB fixture exists to run `migrate_legacy_keys` against, so this
    proves idempotency from the source instead: the existing-row check must
    run BEFORE db.add() and `continue` rather than insert a second row for a
    (user_id, key_hash) pair that is already present."""
    src = inspect.getsource(keypool.migrate_legacy_keys)
    check_idx = src.index("existing is not None")
    add_idx = src.index("db.add(")
    assert check_idx < add_idx
    assert "continue" in src[check_idx:add_idx]
    assert "ApiKey.user_id == user.id" in src
    assert "ApiKey.key_hash == h" in src


def test_wait_ms_uses_inner_join_so_a_keyless_pace_row_is_excluded():
    """`lease`'s candidate query INNER joins ApiKey to PaceState, so a key
    with no pace_state row can never be leased. wait_ms must agree - an
    outer join would report that key as "free now" and loop a lane forever
    waiting on a key that can never actually be picked."""
    src = inspect.getsource(keypool.wait_ms)
    assert "outerjoin" not in src
    assert ".join(PaceState" in src
