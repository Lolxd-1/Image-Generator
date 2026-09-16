"""Dish confidence scoring, concept preview, vessel and Excel category.

One batched `gemini-2.5-flash` call per ~40 items returns all four answers at
once. That batching is deliberate: at one call per item a 100-item menu costs
100 calls before a single image is generated. Batched, it costs three.

Nothing here spends image quota. The admin reviews a *text* concept card, so an
ambiguous dish is never rendered until a human has agreed what it is.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence, TypedDict

from app.engine.gemini import VISION_MODEL, NoImage

try:  # export.py owns the canonical list
    from app.engine.export import EXPORT_FOOD_CATEGORIES
except Exception:  # pragma: no cover - import-order safety net only
    EXPORT_FOOD_CATEGORIES = [
        "Fruits & Vegetables", "Food grains, Oil & Masala", "Bakery", "Dairy",
        "Beverages", "Eggs, Meat & Seafood", "Namkeen, Snacks & Biscuits",
        "Health food", "Instant Food", "Chocolates, desserts and icecream",
        "Mithai (Indian Sweets)", "Baby food", "Gourmet Food", "Pet food",
        "Other Food and Grocery",
    ]

CLASSIFY_BATCH_SIZE = 40
CONFIDENCE_AUTO_APPROVE = 90
CONFIDENCE_LOW = 60

_FALLBACK_CATEGORY = "Other Food and Grocery"


class Classification(TypedDict):
    index: int
    name: str
    confidence: int
    reason: str
    concept: str
    vessel: str
    props: list[str]
    product_category: str


CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "results": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "index": {"type": "INTEGER"},
                    "confidence": {"type": "INTEGER"},
                    "reason": {"type": "STRING"},
                    "concept": {"type": "STRING"},
                    "vessel": {"type": "STRING"},
                    "props": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "product_category": {"type": "STRING"},
                },
                "required": [
                    "index", "confidence", "reason", "concept",
                    "vessel", "props", "product_category",
                ],
            },
        }
    },
    "required": ["results"],
}


CLASSIFY_PROMPT = """You are a food expert preparing a restaurant photo catalogue.

For EACH menu item below, decide how confidently you know what the finished
dish actually looks like on a plate, then describe it.

CONFIDENCE - how certain are you of the dish's appearance?
  95-100  A standard, universally known dish. One obvious appearance.
          "Paneer Butter Masala", "Margherita Pizza", "Cold Coffee",
          "Chicken Biryani", "French Fries".
  75-94   Well known, but with real regional or house-to-house variation in
          presentation. "Veg Hakka Noodles", "Chicken Lollipop".
  60-74   The base ingredient is obvious, but the name carries house-specific
          style words that do not map to one fixed recipe. "Paneer Toofani
          Angara", "Ghiza Surprise Burger", "Chef's Special Chaap".
  30-59   Invented, poetic or branded name where even the main ingredient is a
          guess. "Volcano Delight", "Midnight Special".
  0-29    You genuinely cannot tell what food this is.

Judge only the VISUAL certainty of the finished dish. A dish you know perfectly
scores high even if it is regional. Do not lower a score merely because a name
is Indian, long, or unfamiliar-sounding to a Western reader.

CONCEPT - one vivid sentence describing the plated dish: main components,
colour, texture, garnish. Write it so a photographer could shoot from it alone.
For a low-confidence item, state plainly what you are ASSUMING, because a human
will read this and either approve or correct it. Example for "Paneer Toofani
Angara": "Cubes of paneer in a fiery red, smoky, heavily-spiced onion-tomato
gravy with visible char, finished with cream and coriander."

VESSEL - the serving vessel this dish belongs in. Match the vessel to the FOOD,
never to some default. Curry -> karahi or deep bowl. Rice -> wide handi or
plate. Burger/sandwich -> wooden board. Fries/wings -> fry basket or cone.
Shake -> tall glass. Dessert -> small bowl or coupe. Bread -> cloth-lined basket.

PROPS - up to 3 background items that genuinely belong with this dish:
ingredients, garnishes or accompaniments. Rules:
  - Never the raw, uncooked form of the dish's own main ingredient. No raw
    paneer blocks behind Paneer Masala. No raw chicken behind Fried Chicken.
  - Whole fruit IS correct behind a fruit shake or juice, because it is the
    literal input to the drink.
  - Prefer things a diner would actually see: a dip, a wedge of lemon, fresh
    coriander, whole spices, a folded napkin.
  - Empty list is a perfectly good answer.

PRODUCT_CATEGORY - choose EXACTLY ONE string from this list, copied character
for character:
{categories}

Pick by what the item IS, not by the menu's own section heading. A cold coffee
is "Beverages", not a dessert. A brownie is "Chocolates, desserts and
icecream". Fried chicken is "Eggs, Meat & Seafood". Samosas and fries are
"Namkeen, Snacks & Biscuits". A burger or sandwich is "Instant Food". Use
"Other Food and Grocery" only when nothing else fits.

Return one result object per item, echoing back its `index`. Return a result
for EVERY item, in order. Return strict JSON matching the schema.

ITEMS:
{items}"""


def _build_items_block(items: Sequence[Mapping[str, Any]]) -> str:
    lines = []
    for i, it in enumerate(items):
        name = str(it.get("name") or "").strip()
        cat = str(it.get("category") or "").strip()
        desc = str(it.get("description") or "").strip()
        line = f'{i}. "{name}"'
        if cat:
            line += f" | section: {cat}"
        if desc:
            line += f" | menu note: {desc}"
        lines.append(line)
    return "\n".join(lines)


def _shop_preamble(shop: Mapping[str, Any]) -> str:
    bits = []
    for key, label in (
        ("name", "Shop"),
        ("brand_archetype", "Type"),
        ("cuisine", "Cuisine"),
        ("price_tier", "Price tier"),
        ("plating_style", "Presentation"),
    ):
        val = str(shop.get(key) or "").strip()
        if val:
            bits.append(f"{label}: {val}")
    if not bits:
        return ""
    return (
        "Shop context - use it to judge how elaborate the presentation should "
        "be:\n" + "\n".join(bits) + "\n\n"
    )


def classify_batch(client, shop: Mapping[str, Any],
                   items: Sequence[Mapping[str, Any]]) -> list[Classification]:
    """Classify up to CLASSIFY_BATCH_SIZE items in ONE call.

    Always returns exactly len(items) results, in the same order. A model that
    drops or reorders rows is repaired by index, never by trusting position.
    """
    if not items:
        return []
    from google.genai import types

    prompt = _shop_preamble(shop) + CLASSIFY_PROMPT.format(
        categories="\n".join(f"  - {c}" for c in EXPORT_FOOD_CATEGORIES),
        items=_build_items_block(items),
    )

    resp = client.models.generate_content(
        model=VISION_MODEL,
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CLASSIFY_SCHEMA,
            max_output_tokens=32768,
        ),
    )
    try:
        payload = json.loads(resp.text)
    except (AttributeError, ValueError, TypeError) as exc:
        raise NoImage(f"classify call returned no usable JSON: {exc}") from exc

    raw = payload.get("results") if isinstance(payload, Mapping) else None
    by_index: dict[int, Mapping[str, Any]] = {}
    if isinstance(raw, list):
        for pos, entry in enumerate(raw):
            if not isinstance(entry, Mapping):
                continue
            idx = entry.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(items)):
                idx = pos  # model dropped/garbled the index; fall back to order
            if 0 <= idx < len(items):
                by_index.setdefault(idx, entry)

    return [
        _coerce(by_index.get(i), i, items[i])
        for i in range(len(items))
    ]


def _coerce(entry: Mapping[str, Any] | None, index: int,
            item: Mapping[str, Any]) -> Classification:
    """Turn whatever came back into a safe, complete Classification.

    A missing or malformed row must never crash a 100-item run; it becomes a
    low-confidence item, which simply routes it to human review.
    """
    name = str(item.get("name") or "").strip()
    if entry is None:
        return Classification(
            index=index, name=name, confidence=0,
            reason="The classifier returned no result for this item.",
            concept="", vessel="", props=[],
            product_category=_FALLBACK_CATEGORY,
        )

    try:
        confidence = int(entry.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(100, confidence))

    props_raw = entry.get("props")
    props = (
        [str(p).strip() for p in props_raw if str(p).strip()][:3]
        if isinstance(props_raw, (list, tuple)) else []
    )

    return Classification(
        index=index,
        name=name,
        confidence=confidence,
        reason=_clean(entry.get("reason")),
        concept=_clean(entry.get("concept")),
        vessel=_clean(entry.get("vessel")),
        props=props,
        product_category=_valid_category(entry.get("product_category")),
    )


_WS = re.compile(r"\s+")


def _clean(v: Any) -> str:
    return _WS.sub(" ", str(v).strip()) if isinstance(v, str) else ""


def _valid_category(v: Any) -> str:
    """Constrain to the 15 legal strings; the Excel import rejects anything else."""
    if not isinstance(v, str):
        return _FALLBACK_CATEGORY
    candidate = v.strip()
    for legal in EXPORT_FOOD_CATEGORIES:
        if candidate.lower() == legal.lower():
            return legal  # canonical casing wins
    return _FALLBACK_CATEGORY


def bucket_for(confidence: int | None) -> str:
    """Map a score to the review bucket the UI shows."""
    if confidence is None:
        return "low"
    if confidence >= CONFIDENCE_AUTO_APPROVE:
        return "high"
    if confidence >= CONFIDENCE_LOW:
        return "moderate"
    return "low"
