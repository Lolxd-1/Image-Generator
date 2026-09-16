"""Tests for app.engine.classify's pure helpers, driven through a fake Gemini client.

classify_batch() is never called against the live API here -- a FakeClient
stands in for google.genai.Client so these tests cover the index-realignment
and defensive-coercion logic that keeps one bad model reply from crashing (or
silently corrupting) a 100-item classify run.
"""
import json

import pytest

from app.engine import classify


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, response_text):
        self._response_text = response_text

    def generate_content(self, model, contents, config):
        return _FakeResp(self._response_text)


class _FakeClient:
    def __init__(self, response_text):
        self.models = _FakeModels(response_text)


def _make_client(results):
    return _FakeClient(json.dumps({"results": results}))


def _entry(index, name="", confidence=90, reason="r", concept="c",
           vessel="a bowl", props=None, product_category="Other Food and Grocery"):
    return {
        "index": index, "confidence": confidence, "reason": reason,
        "concept": concept, "vessel": vessel, "props": props or [],
        "product_category": product_category,
    }


SHOP = {"name": "Test Shop"}


def test_well_formed_reply_yields_classifications_in_order():
    items = [{"name": "Idli"}, {"name": "Dosa"}, {"name": "Vada"}]
    results = [
        _entry(0, reason="R0"),
        _entry(1, reason="R1"),
        _entry(2, reason="R2"),
    ]
    client = _make_client(results)
    out = classify.classify_batch(client, SHOP, items)

    assert len(out) == 3
    assert [c["reason"] for c in out] == ["R0", "R1", "R2"]
    assert [c["name"] for c in out] == ["Idli", "Dosa", "Vada"]


def test_dropped_item_defaults_to_confidence_zero():
    items = [{"name": "Idli"}, {"name": "Dosa"}, {"name": "Vada"}]
    # Model only returned results for index 0 and 2; index 1 ("Dosa") is missing.
    results = [_entry(0), _entry(2)]
    client = _make_client(results)
    out = classify.classify_batch(client, SHOP, items)

    assert len(out) == 3  # never fewer than len(items)
    assert out[1]["confidence"] == 0
    assert out[1]["name"] == "Dosa"
    assert classify.bucket_for(out[1]["confidence"]) == "low"  # routes to human review


def test_scrambled_index_is_realigned_not_taken_by_position():
    items = [{"name": "Idli"}, {"name": "Dosa"}, {"name": "Vada"}]
    # List order is scrambled; the `index` field, not list position, must win.
    results = [
        _entry(2, reason="R2"),
        _entry(0, reason="R0"),
        _entry(1, reason="R1"),
    ]
    client = _make_client(results)
    out = classify.classify_batch(client, SHOP, items)

    assert out[0]["reason"] == "R0"
    assert out[1]["reason"] == "R1"
    assert out[2]["reason"] == "R2"


def test_garbled_index_falls_back_to_list_position():
    items = [{"name": "Idli"}, {"name": "Dosa"}]
    results = [
        _entry("not-an-int", reason="first"),
        _entry(99, reason="second"),  # out of range
    ]
    client = _make_client(results)
    out = classify.classify_batch(client, SHOP, items)

    assert len(out) == 2
    assert out[0]["reason"] == "first"
    assert out[1]["reason"] == "second"


def test_invalid_product_category_coerced_to_fallback():
    items = [{"name": "Mystery Dish"}]
    results = [_entry(0, product_category="Not A Real Category")]
    client = _make_client(results)
    out = classify.classify_batch(client, SHOP, items)

    assert out[0]["product_category"] == "Other Food and Grocery"


def test_valid_product_category_preserved_with_canonical_casing():
    items = [{"name": "Cold Coffee"}]
    results = [_entry(0, product_category="beverages")]  # wrong case
    client = _make_client(results)
    out = classify.classify_batch(client, SHOP, items)

    assert out[0]["product_category"] == "Beverages"


@pytest.mark.parametrize("raw,expected", [(150, 100), (-10, 0), (100, 100), (0, 0), (55, 55)])
def test_confidence_is_clamped_to_0_100(raw, expected):
    items = [{"name": "X"}]
    results = [_entry(0, confidence=raw)]
    client = _make_client(results)
    out = classify.classify_batch(client, SHOP, items)

    assert out[0]["confidence"] == expected


@pytest.mark.parametrize("confidence,bucket", [
    (100, "high"), (90, "high"),
    (89, "moderate"), (60, "moderate"),
    (59, "low"), (0, "low"),
    (None, "low"),
])
def test_bucket_for(confidence, bucket):
    assert classify.bucket_for(confidence) == bucket
