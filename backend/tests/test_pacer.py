"""Pure-maths tests for app.engine.pacer: grow/shrink/backoff. No DB involved.

These constants were tuned by hand against a flaky free-tier quota (per the
module docstring) and must never be silently re-tuned; these tests pin the
exact multipliers and clamps.
"""
import pytest

from app.engine import pacer


def test_grow_multiplies_by_rate_grow():
    assert pacer.grow(30.0) == pytest.approx(30.0 * 1.5)


def test_grow_clamps_at_rate_max_delay():
    assert pacer.grow(pacer.RATE_MAX_DELAY) == pacer.RATE_MAX_DELAY
    assert pacer.grow(1000.0) == pacer.RATE_MAX_DELAY


def test_shrink_multiplies_by_rate_shrink():
    assert pacer.shrink(30.0) == pytest.approx(30.0 * 0.92)


def test_shrink_clamps_at_rate_min_delay():
    assert pacer.shrink(pacer.RATE_MIN_DELAY) == pacer.RATE_MIN_DELAY
    assert pacer.shrink(0.001) == pacer.RATE_MIN_DELAY


def test_backoff_first_call_is_backoff_base_not_double():
    """The first 429 must wait RATE_BACKOFF_BASE (20s), not 40s."""
    assert pacer.backoff(0) == pacer.RATE_BACKOFF_BASE
    assert pacer.backoff(0) == 20.0


def test_backoff_doubles_each_attempt():
    assert pacer.backoff(1) == pacer.RATE_BACKOFF_BASE * 2
    assert pacer.backoff(2) == pacer.RATE_BACKOFF_BASE * 4


def test_backoff_capped_at_rate_backoff_max():
    assert pacer.backoff(20) == pacer.RATE_BACKOFF_MAX


def test_constants_match_spec():
    assert pacer.RATE_START_DELAY == 30.0
    assert pacer.RATE_MIN_DELAY == 8.0
    assert pacer.RATE_MAX_DELAY == 120.0
    assert pacer.RATE_GROW == 1.5
    assert pacer.RATE_SHRINK == 0.92
    assert pacer.RATE_BACKOFF_BASE == 20.0
    assert pacer.RATE_BACKOFF_MAX == 300.0
