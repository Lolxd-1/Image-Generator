"""Tests for the pure helpers in app.engine.extract: normalise_items, merge, parse_price.

No Gemini call, no I/O -- these are the functions that decide whether the same
dish photographed twice becomes one catalogue row or two, and whether a
genuine price disagreement between two menu photos is silently dropped.
"""
import pytest

from app.engine import extract


# ---------------------------------------------------------------------------
# parse_price
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("₹120", 120.0),
    ("120.50", 120.5),
    ("1,200", 1200.0),
    ("", None),
    (None, None),
])
def test_parse_price(raw, expected):
    assert extract.parse_price(raw) == expected


def test_parse_price_rejects_zero_and_negative():
    assert extract.parse_price(0) is None
    assert extract.parse_price(-5) is None


def test_parse_price_rejects_absurdly_large_values():
    assert extract.parse_price(1_000_000) is None


def test_parse_price_accepts_numeric_types_directly():
    assert extract.parse_price(99) == 99.0
    assert extract.parse_price(99.5) == 99.5


# ---------------------------------------------------------------------------
# normalise_items
# ---------------------------------------------------------------------------

def test_normalise_items_drops_items_with_no_usable_price():
    raw = [{"item_name": "Mystery Item", "category": "Misc", "price": "N/A"}]
    items, warns = extract.normalise_items(raw, "photo1.jpg")
    assert items == []
    assert any("dropped" in w for w in warns)


def test_normalise_items_drops_items_with_no_name():
    raw = [{"item_name": "", "category": "Misc", "price": 50}]
    items, warns = extract.normalise_items(raw, "photo1.jpg")
    assert items == []


def test_normalise_items_truncates_long_names():
    raw = [{"item_name": "x" * 250, "category": "Misc", "price": 50}]
    items, warns = extract.normalise_items(raw, "photo1.jpg")
    assert len(items[0]["item_name"]) == 200
    assert any("truncated" in w for w in warns)


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

def _item(name, category, price, source):
    return {
        "item_name": name, "category": category, "price": price,
        "description": "", "source": source,
    }


def test_merge_dedupes_same_item_on_two_photos():
    per_photo = [
        ("photo1.jpg", [_item("Paneer Tikka", "Starters", 200.0, "photo1.jpg")]),
        ("photo2.jpg", [_item("Paneer Tikka", "Starters", 200.0, "photo2.jpg")]),
    ]
    merged, notes = extract.merge(per_photo)

    assert len(merged) == 1
    assert any("duplicate skipped" in n for n in notes)


def test_merge_dedupe_is_case_and_punctuation_insensitive():
    per_photo = [
        ("photo1.jpg", [_item("Paneer Tikka", "Starters", 200.0, "photo1.jpg")]),
        ("photo2.jpg", [_item("paneer-tikka", "STARTERS", 200.0, "photo2.jpg")]),
    ]
    merged, notes = extract.merge(per_photo)
    assert len(merged) == 1


def test_merge_flags_price_conflict_and_keeps_both_rows():
    per_photo = [
        ("photo1.jpg", [_item("Paneer Tikka", "Starters", 200.0, "photo1.jpg")]),
        ("photo2.jpg", [_item("Paneer Tikka", "Starters", 220.0, "photo2.jpg")]),
    ]
    merged, notes = extract.merge(per_photo)

    assert len(merged) == 2  # both kept for a human to glance at
    assert any("PRICE CONFLICT" in n for n in notes)


def test_merge_keeps_distinct_items_untouched():
    per_photo = [
        ("photo1.jpg", [
            _item("Paneer Tikka", "Starters", 200.0, "photo1.jpg"),
            _item("Veg Biryani", "Main Course", 180.0, "photo1.jpg"),
        ]),
    ]
    merged, notes = extract.merge(per_photo)
    assert len(merged) == 2
    assert notes == []
