"""Layered prompt construction for dish image generation.

The original CLI tool hardcoded one reference photo's look into English prose
("the solid pale green background", "do NOT copy the copper kadhai"). That text
is a lie the moment a different reference image is uploaded, and it silently
degrades every generated image.

Here the style is *derived* from whatever reference the admin uploads, once per
shop, and composed with three other independent layers:

    LAYER 1  STYLE            derive_style_profile()  - one vision call per shop
    LAYER 2  SHOP CONTEXT     the 7 setup metrics
    LAYER 3  DISH             name/category/description + AI vessel & props
    LAYER 4  ANTI-REPETITION  computed, not AI: vessel/prop exclusions + variation

Layer 4 is what stops 100 dishes arriving in 100 identical bowls.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence, TypedDict

from app.engine.gemini import VISION_MODEL, NoImage

# ---------------------------------------------------------------------------
# LAYER 1 - style derived from the reference image
# ---------------------------------------------------------------------------


class StyleProfile(TypedDict):
    camera_angle: str
    lighting: str
    surface: str
    background: str
    colour_palette: list[str]
    mood: str
    vessel_in_reference: str
    props_in_reference: list[str]


STYLE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "camera_angle": {"type": "STRING"},
        "lighting": {"type": "STRING"},
        "surface": {"type": "STRING"},
        "background": {"type": "STRING"},
        "colour_palette": {"type": "ARRAY", "items": {"type": "STRING"}},
        "mood": {"type": "STRING"},
        "vessel_in_reference": {"type": "STRING"},
        "props_in_reference": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": [
        "camera_angle", "lighting", "surface", "background",
        "colour_palette", "mood", "vessel_in_reference", "props_in_reference",
    ],
}

STYLE_PROMPT = """You are a food photography director analysing ONE reference photograph.

Describe only what is PHOTOGRAPHICALLY reusable for other, unrelated dishes.

- camera_angle: the exact viewpoint, e.g. "45-degree three-quarter view",
  "top-down flat lay", "straight-on eye level".
- lighting: direction, hardness and shadow behaviour, e.g. "bright directional
  key from upper left, hard distinct shadows, no fill".
- surface: what the food sits ON, e.g. "textured light stone slab with a dark
  wooden baseboard".
- background: the backdrop BEHIND the food, e.g. "solid pale green seamless",
  "dark moody blur". Describe colour and whether it is solid or textured.
- colour_palette: 3-5 dominant colours as plain names.
- mood: 3-6 words, e.g. "premium, earthy, appetising, editorial".

These two are the most important. They record what must NOT be copied onto
other dishes, because they belong to THIS dish only:

- vessel_in_reference: the exact serving vessel, e.g. "a copper kadhai with
  twin handles", "a matte black ceramic bowl". If there is no vessel, say
  "none".
- props_in_reference: every decorative or ingredient prop staged around the
  food, e.g. ["a small bowl of red chilli powder", "scattered dry red
  chillies", "a folded grey napkin"]. Empty list if none.

Return strict JSON matching the schema. Describe only what you can actually
see. Never mention the specific dish or its ingredients."""


def derive_style_profile(client, ref_jpeg: bytes) -> StyleProfile:
    """One vision call per shop. Result is cached in shops.style_profile."""
    from google.genai import types

    resp = client.models.generate_content(
        model=VISION_MODEL,
        contents=[
            types.Part.from_bytes(data=ref_jpeg, mime_type="image/jpeg"),
            STYLE_PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=STYLE_SCHEMA,
            max_output_tokens=2048,
        ),
    )
    try:
        data = json.loads(resp.text)
    except (AttributeError, ValueError, TypeError) as exc:
        raise NoImage(f"style profile call returned no usable JSON: {exc}") from exc
    return _coerce_style(data)


def _coerce_style(data: Mapping[str, Any]) -> StyleProfile:
    """Never trust the model's shape; fill gaps with neutral, harmless values."""
    def s(key: str, default: str) -> str:
        v = data.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else default

    def lst(key: str) -> list[str]:
        v = data.get(key)
        if not isinstance(v, (list, tuple)):
            return []
        return [str(x).strip() for x in v if str(x).strip()]

    return StyleProfile(
        camera_angle=s("camera_angle", "45-degree three-quarter view"),
        lighting=s("lighting", "bright directional lighting with soft shadows"),
        surface=s("surface", "a clean neutral surface"),
        background=s("background", "a plain uncluttered background"),
        colour_palette=lst("colour_palette"),
        mood=s("mood", "premium, appetising"),
        vessel_in_reference=s("vessel_in_reference", "none"),
        props_in_reference=lst("props_in_reference"),
    )


NEUTRAL_STYLE: StyleProfile = _coerce_style({})


# ---------------------------------------------------------------------------
# LAYER 4a - vessel selection
# ---------------------------------------------------------------------------

# Ordered: the FIRST pattern that matches wins, so put specific before generic.
# Matched against "<name> <category>" lowercased.
VESSEL_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(shake|smoothie|thickshake|lassi|falooda)\b"),
     "a tall frosted milkshake glass"),
    (re.compile(r"\b(mojito|mocktail|cooler|soda|juice|iced tea|lemonade)\b"),
     "a tall clear highball glass with ice"),
    (re.compile(r"\b(coffee|cappuccino|latte|espresso|tea|chai)\b"),
     "a ceramic cup on a matching saucer"),
    (re.compile(r"\b(ice cream|sundae|gelato|kulfi|falooda)\b"),
     "a chilled dessert coupe"),
    (re.compile(r"\b(brownie|pastry|cake|waffle|pancake|donut|muffin)\b"),
     "a small flat dessert plate"),
    (re.compile(r"\b(burger|sandwich|sub|wrap|roll|twister|taco)\b"),
     "a rustic wooden serving board with parchment"),
    (re.compile(r"\b(pizza)\b"), "a round wooden pizza board"),
    (re.compile(r"\b(fries|nachos|popcorn|nuggets|wings|lollipop|tenders|strips)\b"),
     "a fry basket lined with printed paper"),
    (re.compile(r"\b(bucket|family pack|combo|meal box)\b"),
     "a branded serving bucket with pieces spilling out"),
    (re.compile(r"\b(biryani|pulao|rice|fried rice|khichdi)\b"),
     "a wide shallow copper handi"),
    (re.compile(r"\b(noodles|hakka|chowmein|pasta|spaghetti|ramen)\b"),
     "a deep wide ceramic pasta bowl"),
    (re.compile(r"\b(soup|shorba|broth)\b"), "a deep soup bowl on a liner plate"),
    (re.compile(r"\b(naan|roti|paratha|kulcha|bread|puri|bhatura)\b"),
     "a cloth-lined bread basket"),
    (re.compile(r"\b(tikka|kebab|seekh|tandoori|grill|roast|bbq|barbecue)\b"),
     "a sizzling cast-iron platter with onion rings and lemon"),
    (re.compile(r"\b(dosa|uttapam|idli|vada)\b"),
     "a traditional steel or banana-leaf-lined plate"),
    (re.compile(r"\b(chaat|tikki|samosa|pakora|bhaji|vada pav|pav)\b"),
     "a small steel serving plate"),
    (re.compile(r"\b(thali|platter)\b"), "a sectioned steel thali"),
    (re.compile(r"\b(raita|chutney|dip|sauce|mayo|salad)\b"),
     "a small condiment bowl"),
    (re.compile(r"\b(curry|masala|gravy|korma|makhani|butter|handi|kadhai|karahi"
                r"|paneer|chaap|kofta|dal|sabzi|do pyaza|angara)\b"),
     "a traditional karahi with short handles"),
]

_DEFAULT_VESSEL = "a serving dish that suits the food"

# Vessel words we accept from the model without second-guessing it.
_VESSEL_VOCAB = re.compile(
    r"\b(bowl|plate|platter|board|basket|glass|cup|mug|kadhai|karahi|handi|"
    r"thali|tray|bucket|cone|skillet|pan|dish|coupe|saucer|jar|tumbler|"
    r"ramekin|casserole|leaf)\b",
    re.I,
)


def vessel_for(item_name: str, category: str, suggested: str | None = None) -> str:
    """Pick serveware for a dish.

    The classifier's suggestion wins when it names a real vessel; otherwise the
    rule table decides. This is what keeps a dry snack out of a curry bowl.
    """
    if suggested:
        s = suggested.strip()
        if s and s.lower() != "none" and _VESSEL_VOCAB.search(s):
            return s if s[0].isupper() is False else s
    haystack = f"{item_name} {category}".lower()
    for pattern, vessel in VESSEL_RULES:
        if pattern.search(haystack):
            return vessel
    return _DEFAULT_VESSEL


# ---------------------------------------------------------------------------
# LAYER 4b - prop sanitising
# ---------------------------------------------------------------------------

# Hero proteins/bases that must never appear RAW beside their own cooked dish.
# Nobody stages raw paneer blocks behind a finished Paneer Masala.
_HERO_INGREDIENTS = [
    "paneer", "chicken", "mutton", "lamb", "beef", "pork", "fish", "prawn",
    "shrimp", "egg", "soya", "chaap", "tofu", "mushroom", "keema",
]

# Drinks whose literal raw input IS a legitimate prop (blueberries behind a
# blueberry shake are correct; raw chicken behind fried chicken is not).
_FRUIT_FORWARD = re.compile(
    r"\b(shake|smoothie|juice|mojito|cooler|iced tea|lemonade|falooda|sundae|"
    r"lassi|mocktail)\b", re.I,
)

_RAW_WORDS = re.compile(r"\braw\b|\buncooked\b|\bblock[s]?\b|\bslab[s]?\b", re.I)


def sanitize_props(item_name: str, category: str,
                   props: Sequence[str] | None) -> list[str]:
    """Drop props that would look absurd next to this specific dish."""
    if not props:
        return []
    haystack = f"{item_name} {category}".lower()
    drink_like = bool(_FRUIT_FORWARD.search(haystack))
    cleaned: list[str] = []
    for raw_prop in props:
        prop = str(raw_prop).strip()
        if not prop or prop.lower() == "none":
            continue
        low = prop.lower()
        # A raw form of the dish's own hero ingredient is never acceptable,
        # regardless of what the model suggested.
        hero_hit = any(h in low and h in haystack for h in _HERO_INGREDIENTS)
        if hero_hit and (_RAW_WORDS.search(low) or low.strip() in _HERO_INGREDIENTS):
            continue
        if hero_hit and not drink_like and _RAW_WORDS.search(low):
            continue
        cleaned.append(prop)
        if len(cleaned) >= 3:
            break
    return cleaned


# ---------------------------------------------------------------------------
# LAYER 4c - per-item variation
# ---------------------------------------------------------------------------

# Small, safe deltas. They never fight the style profile - they vary only what
# the style profile does not pin down.
VARIATION_HINTS = [
    "Compose the dish slightly left of centre with breathing room on the right.",
    "Compose the dish centred, filling a generous portion of the frame.",
    "Compose the dish slightly right of centre, with the garnish facing camera.",
    "Frame a little tighter on the food so texture detail reads clearly.",
    "Allow a little more negative space above the dish.",
    "Angle the vessel a few degrees so its rim is not perfectly parallel.",
]


def _variation(seed: int) -> str:
    return VARIATION_HINTS[seed % len(VARIATION_HINTS)]


# ---------------------------------------------------------------------------
# LAYER 2 - shop context
# ---------------------------------------------------------------------------

_PROP_DENSITY = {
    0: "Stage NO background props at all. The dish alone.",
    1: "Stage at most one subtle background prop. Keep it sparse and clean.",
    2: "Stage two or three background props, balanced and uncrowded.",
    3: "Stage a richer arrangement of props, still subordinate to the dish.",
}


def _shop_sentence(shop: Mapping[str, Any]) -> str:
    bits: list[str] = []
    name = (shop.get("name") or "").strip()
    archetype = (shop.get("brand_archetype") or "").strip()
    cuisine = (shop.get("cuisine") or "").strip()
    tier = (shop.get("price_tier") or "").strip()
    plating = (shop.get("plating_style") or "").strip()

    lead = " ".join(x for x in [tier, archetype] if x)
    if name and lead:
        bits.append(f'This is for "{name}", a {lead}.')
    elif name:
        bits.append(f'This is for "{name}".')
    elif lead:
        bits.append(f"This is for a {lead}.")

    if cuisine:
        bits.append(f"Cuisine: {cuisine}.")
    if plating:
        bits.append(f"Presentation should read as: {plating}.")
    return " ".join(bits)


# ---------------------------------------------------------------------------
# The composed prompt
# ---------------------------------------------------------------------------


def build_prompt(style: Mapping[str, Any] | None,
                 shop: Mapping[str, Any],
                 item: Mapping[str, Any],
                 seed: int = 0) -> str:
    """Compose the four layers into one image-generation prompt."""
    st: StyleProfile = _coerce_style(style or {})

    name = str(item.get("name") or "").strip()
    category = str(item.get("category") or "").strip()
    description = str(item.get("description") or "").strip()
    concept = str(item.get("concept_text") or "").strip()

    vessel = vessel_for(name, category, item.get("suggested_vessel"))
    props = sanitize_props(name, category, item.get("suggested_props"))

    # --- LAYER 3: what the dish actually is -------------------------------
    dish_bits = [f'"{name}"']
    if category:
        dish_bits.append(f"Category: {category}")
    if description:
        dish_bits.append(f"Menu description: {description}")
    if concept:
        dish_bits.append(f"What the dish looks like: {concept}")
    dish_context = ". ".join(dish_bits)

    parts: list[str] = [
        f'A professional food photograph of "{name}".',
        f"DISH: {dish_context}.",
        "Represent the dish accurately - its real ingredients, texture, colour "
        "and portion. The food itself is the subject and must be the sharpest, "
        "most appetising element in the frame.",
    ]

    # --- LAYER 2: brand identity ------------------------------------------
    shop_sentence = _shop_sentence(shop)
    if shop_sentence:
        parts.append(f"BRAND CONTEXT: {shop_sentence}")

    # --- LAYER 1: the derived house style ---------------------------------
    palette = ", ".join(st["colour_palette"][:5])
    style_lines = [
        f"Camera: {st['camera_angle']}.",
        f"Lighting: {st['lighting']}.",
        f"Surface: {st['surface']}.",
        f"Background: {st['background']}.",
        f"Mood: {st['mood']}.",
    ]
    if palette:
        style_lines.append(f"Overall colour palette: {palette}.")
    parts.append(
        "HOUSE STYLE - match the reference photograph's photography exactly: "
        + " ".join(style_lines)
    )

    # --- LAYER 4: anti-repetition -----------------------------------------
    parts.append(
        f"SERVEWARE: Serve this dish in {vessel}. The vessel must suit THIS "
        f"dish specifically, and must match the premium feel of the scene."
    )
    ref_vessel = st["vessel_in_reference"]
    if ref_vessel and ref_vessel.lower() != "none":
        parts.append(
            f"DO NOT reuse the serving vessel from the reference photograph "
            f"({ref_vessel}) unless it genuinely suits this dish. Copy the "
            f"reference's photography, never its crockery."
        )

    density = _PROP_DENSITY.get(int(shop.get("prop_density") or 1), _PROP_DENSITY[1])
    if props:
        parts.append(
            f"BACKGROUND PROPS: {density} Use only props that genuinely belong "
            f"with this dish: {', '.join(props)}. Keep them soft and out of "
            f"focus behind the food."
        )
    else:
        parts.append(
            f"BACKGROUND PROPS: {density} Any prop must be an ingredient or "
            f"accompaniment that genuinely belongs with this dish."
        )

    ref_props = st["props_in_reference"]
    if ref_props:
        parts.append(
            "DO NOT reuse the reference photograph's props "
            f"({', '.join(ref_props[:4])}). They belong to that dish, not this one."
        )

    parts.append(
        "Never scatter raw or uncooked forms of the dish's own main ingredient "
        "in the scene. Never include text, logos, watermarks, hands or cutlery "
        "in use."
    )

    notes = str(shop.get("notes") or "").strip()
    if notes:
        parts.append(f"ADDITIONAL RULES: {notes}")

    parts.append(_variation(seed))
    parts.append("The image must be perfectly square (1:1 aspect ratio).")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Fallback ladder - progressively plainer prompts when one gets blocked
# ---------------------------------------------------------------------------


def fallback_prompt(name: str, description: str, category: str, attempt: int,
                    style: Mapping[str, Any] | None = None) -> str:
    """A blocked prompt rarely unblocks itself; strip detail each time.

    Ported from the original tool's ladder, but the style words are taken from
    the derived profile instead of being hardcoded to one reference photo.
    """
    st: StyleProfile = _coerce_style(style or {})
    if attempt <= 0:
        return (
            f'A professional food photograph of "{name}". '
            f"Match the photography style, lighting, surface and background of "
            f"the reference image ({st['background']}). "
            f"Serve the dish in a vessel that suits it. Square 1:1 composition."
        )
    if attempt == 1:
        ctx = f" ({category})" if category else ""
        return (
            f"Professional food photography of {name}{ctx}, {st['camera_angle']}, "
            f"{st['lighting']}, {st['surface']}, {st['background']}, "
            f"square composition."
        )
    return f"An appetizing photo of {name} on a plate, plain pale background."
