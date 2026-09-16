"""Menu-photo extraction: the Gemini vision prompt/schema and the pure item-normalisation helpers, ported from extract_menu.py.

`RESPONSE_SCHEMA`, `EXTRACT_PROMPT`, `normalise_items`, `merge`, `clean_text`,
`norm_key` and `parse_price` are copied verbatim — the prompt in particular is
a long, carefully tuned string and must not be reworded. File/cache/Excel I/O
from the original CLI tool is stripped out; this module is pure functions over
bytes and dicts.
"""
import json
import re
import time
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageOps
from google.genai import types

from app.engine import gemini

MAX_DIM = 1600             # downscale before upload - keeps small print legible
JPEG_QUALITY = 92
MAX_OUTPUT_TOKENS = 32768  # a very dense board can emit a lot of JSON

# Retry tuning for the vision call itself (extract_menu.py's MenuReader.read).
# Distinct from pacer.py's image-generation constants - the vision quota is
# far kinder than the image-gen quota.
MAX_RETRIES = 5
RATE_BACKOFF_BASE = 10.0
RATE_BACKOFF_MAX = 120.0

# ============================================================
# PROMPT  (extract_menu.py lines 115-176, verbatim)
# ============================================================

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_menu": {"type": "BOOLEAN"},
        "restaurant_name": {"type": "STRING"},
        "currency": {"type": "STRING"},
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "item_name": {"type": "STRING"},
                    "category": {"type": "STRING"},
                    "price": {"type": "NUMBER"},
                    "description": {"type": "STRING"},
                },
                "required": ["item_name", "category", "price"],
            },
        },
    },
    "required": ["is_menu", "items"],
}

EXTRACT_PROMPT = """You are reading a photograph of a restaurant menu (a menu board, printed card, or leaflet).

Extract EVERY purchasable item that has a price printed next to it.

Rules:
1. ONE ROW PER PRICE. If an item shows several prices under column headings
   (Large/Small, Double layer/Single layer, Half/Full, Box of 4/Box of 6),
   emit one row per price and put the variant in the name:
   "Choco Brownie Sundae (Large)", "Almond Brownie Cake (Double Layer)".
2. If a single name contains a slash for interchangeable options
   ("Honey Butter/Maple Butter", "Iced Tea (Lemon/Peach)"), that is ONE item -
   emit one row and keep the name exactly as printed.
3. category = the most specific section heading printed above the item
   ("Classics", "Shakes", "Waffle Cakes", "Coolers"). Never invent a category.
   If the section has a parent heading, use the specific child heading.
   Do NOT repeat the category inside the item name. Under a "Mini Waff-wich
   Combos" heading, "Box of 4 / Chocoholic's" becomes item_name
   "Chocoholic's (Box of 4)" with category "Mini Waff-wich Combos" - never
   "Mini Waff-wich Combos Box of 4 Chocoholic's".
4. price = the number only. No currency symbol, no commas.
5. description = the small print printed under that item, if any. Otherwise "".
6. Copy names EXACTLY as printed, including accents. Fix only obvious OCR
   damage, never re-word or expand a name.
7. A priced upgrade or add-on IS an item ("Add an ice-cream scoop - Rs 30",
   "Turn any Classic No-Maida - Rs 30"). Category it exactly like anything
   else: use its printed section heading if it sits under one (a toppings
   block headed "Extra Goodness" stays "Extra Goodness"). Only use "Add-ons"
   for a standalone priced banner that has no section heading at all.
8. IGNORE anything with no price of its own: allergen and copyright notices,
   GST lines, phone numbers, addresses, social handles, opening hours,
   decorative slogans, and any adjacent poster, screen or signboard that is not
   part of this menu itself.
9. Do NOT guess. If a price or a name is genuinely unreadable in the photo,
   skip that item rather than inventing a value.
10. Set is_menu=false and items=[] if this photograph is not a menu at all.

Return strict JSON matching the schema."""


# ============================================================
# IMAGE PREP
# ============================================================

def prepare_image(data: bytes) -> bytes:
    """Downscale to MAX_DIM and re-encode as JPEG."""
    im = Image.open(BytesIO(data))
    # honour EXIF rotation - a sideways photo reads badly
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    im = im.convert("RGB")
    if max(im.size) > MAX_DIM:
        im.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


# ============================================================
# GEMINI VISION
# ============================================================

def read_menu(client, image_bytes: bytes) -> dict:
    """Read one prepared menu photo. Returns the parsed dict. Raises on final failure.

    `image_bytes` is expected to already be the output of `prepare_image`.
    Retry/backoff logic ported from extract_menu.py's MenuReader.read; the
    backup-key switch from the original CLI is dropped — the web app has one
    Gemini key per user, not a primary/backup pair.
    """
    part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        temperature=0.0,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    last_err = "unknown error"
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.models.generate_content(
                model=gemini.VISION_MODEL, contents=[part, EXTRACT_PROMPT], config=config,
            )
        except Exception as e:
            msg = str(e)
            last_err = f"{type(e).__name__}: {msg[:250]}"
            if gemini.is_rate_limit(msg):
                wait = min(RATE_BACKOFF_BASE * (2 ** attempt), RATE_BACKOFF_MAX)
                time.sleep(wait)
                continue
            if gemini.is_auth_error(msg):
                raise gemini.AuthFailure(f"AUTH/BILLING FAILURE: {msg[:250]}") from e
            wait = min(4 * (2 ** attempt), 45)
            time.sleep(wait)
            continue

        text = (resp.text or "").strip()
        if not text:
            last_err = f"empty response (finish_reason={gemini.finish_reason(resp)})"
            time.sleep(3)
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            # Nearly always a token-truncated response.
            last_err = f"invalid JSON ({e}); {len(text)} chars returned"
            time.sleep(3)
            continue

        if not isinstance(data, dict) or "items" not in data:
            last_err = f"unexpected JSON shape: {str(data)[:150]}"
            time.sleep(3)
            continue
        return data

    raise RuntimeError(last_err)


# ============================================================
# NORMALISE + MERGE  (extract_menu.py lines 355-435, verbatim)
# ============================================================

_WS = re.compile(r"\s+")


def clean_text(v) -> str:
    return _WS.sub(" ", str(v or "")).strip()


def norm_key(name: str, category: str) -> str:
    """Dedupe key: case/space/punctuation-insensitive name + category.

    Must be UNICODE-aware. The original tool used `[^a-z0-9]+`, which only
    ever saw English menus; on a Devanagari (or Tamil, Bengali, Arabic...)
    menu it strips EVERY character, so all 83 dishes collapse to the same
    empty key, get deduped down to one, and emit dozens of phantom "price
    conflict" warnings. `str.isalnum()` is true for letters and digits in
    any script, so this keeps the same case/punctuation insensitivity
    without discarding non-Latin names.
    """
    def squash(s: str) -> str:
        return "".join(ch for ch in (s or "").casefold() if ch.isalnum())
    return f"{squash(name)}|{squash(category)}"


def parse_price(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        p = float(v)
    else:
        s = re.sub(r"[^\d.]", "", str(v))
        if not s:
            return None
        try:
            p = float(s)
        except ValueError:
            return None
    if p <= 0 or p > 999999:
        return None
    return round(p, 2)


def normalise_items(raw: List[dict], source: str) -> Tuple[List[dict], List[str]]:
    """Clean one photo's items. Returns (items, warnings)."""
    items, warns = [], []
    for r in raw or []:
        name = clean_text(r.get("item_name"))
        if not name:
            continue
        if len(name) > 200:
            warns.append(f"{source}: '{name[:40]}...' name truncated to 200 chars")
            name = name[:200]
        price = parse_price(r.get("price"))
        if price is None:
            warns.append(f"{source}: '{name}' has no usable price ({r.get('price')!r}) - dropped")
            continue
        items.append({
            "item_name": name,
            "category": clean_text(r.get("category")),
            "price": price,
            "description": clean_text(r.get("description"))[:2000],
            "source": source,
        })
    return items, warns


def merge(per_photo: List[Tuple[str, List[dict]]]) -> Tuple[List[dict], List[str]]:
    """Concatenate photos in order, dropping repeats across overlapping shots."""
    seen: Dict[str, dict] = {}
    merged, notes = [], []
    for source, items in per_photo:
        for it in items:
            k = norm_key(it["item_name"], it["category"])
            prev = seen.get(k)
            if prev is None:
                seen[k] = it
                merged.append(it)
                continue
            if abs(prev["price"] - it["price"]) < 0.01:
                notes.append(
                    f"duplicate skipped: '{it['item_name']}' ({it['category']}) "
                    f"also in {prev['source']}")
            else:
                # Same name+category, different price -> genuinely different rows
                # (or a misread). Keep both and flag it for a human to glance at.
                notes.append(
                    f"PRICE CONFLICT: '{it['item_name']}' ({it['category']}) = "
                    f"{prev['price']:g} in {prev['source']} but {it['price']:g} "
                    f"in {source} - both kept")
                merged.append(it)
    return merged, notes
