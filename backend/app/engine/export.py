"""SmartBiz bulk-upload workbook: category mapping and row validation, ported from smartbiz_export.py.

`product_category_for`'s keyword matcher is ported verbatim, including its
word-boundary fix (a plain substring test files "Classics" under Beverages
because "c-LASSI-cs" contains "lassi"). `build_workbook` writes into a COPY of
the real `templates/smartbiz_template.xlsx` — building a fresh workbook loses
the template's 29 data validations and the SmartBiz import fails.
"""
from decimal import Decimal, InvalidOperation
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

import openpyxl

TEMPLATE_PATH = "templates/smartbiz_template.xlsx"
SHEET = "bulk_upload_template"

# 1-indexed columns in the template.
COL_NAME = 4
COL_MRP = 5
COL_SELLING = 6
COL_BUSINESS_CAT = 7
COL_PRODUCT_CAT = 8
COL_DESCRIPTION = 9
COL_IMAGE1 = 16

MAX_NAME = 200
MAX_DESC = 2000
MAX_MRP = 999999.99

# `templates/` lives at webapp/backend/templates/; this module is at
# webapp/backend/app/engine/export.py.
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _template_full_path() -> Path:
    return _BACKEND_DIR / TEMPLATE_PATH


# The only legal column-H (Product Category) values for a FOOD_AND_GROCERY
# business, per the template's DataSheet dropdown.
EXPORT_FOOD_CATEGORIES = [
    "Fruits & Vegetables", "Food grains, Oil & Masala", "Bakery", "Dairy",
    "Beverages", "Eggs, Meat & Seafood", "Namkeen, Snacks & Biscuits",
    "Health food", "Instant Food", "Chocolates, desserts and icecream",
    "Mithai (Indian Sweets)", "Baby food", "Gourmet Food", "Pet food",
    "Other Food and Grocery",
]

# smartbiz_export.py lines 66-79, verbatim. Matched on the menu category text,
# used only as a fallback when the AI-suggested category isn't usable.
CATEGORY_KEYWORDS = [
    ("milkshake", "Beverages"),
    ("smoothie", "Beverages"),
    ("mocktail", "Beverages"),
    ("beverage", "Beverages"),
    ("cooler", "Beverages"),
    ("coffee", "Beverages"),
    ("shake", "Beverages"),
    ("juice", "Beverages"),
    ("lassi", "Beverages"),
    ("drink", "Beverages"),
    ("soda", "Beverages"),
    ("tea", "Beverages"),
]


def product_category_for(menu_category: str, ai_suggestion: Optional[str], default: str) -> str:
    """Resolve the SmartBiz Product Category (column H) for one item.

    1. `ai_suggestion` if it is one of the legal EXPORT_FOOD_CATEGORIES.
    2. Else the keyword map, matched on `menu_category`. The keyword must
       START A WORD, not merely appear somewhere in the text: a plain
       substring test files "Classics" under Beverages, because "c-LASSI-cs"
       contains "lassi". A trailing \\w* still catches the plurals real menus
       use ("Shakes", "Coolers", "Juices").
    3. Else `default`.
    """
    if ai_suggestion and ai_suggestion in EXPORT_FOOD_CATEGORIES:
        return ai_suggestion

    text = (menu_category or "").lower()
    for keyword, smartbiz_cat in CATEGORY_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\w*", text):
            return smartbiz_cat

    return default


@dataclass
class RowError:
    row: int
    item_id: str
    field: str
    message: str


# SPEC-GAP: SPEC.md does not pin down the exact dict shape of `rows` for
# validate()/build_workbook() — app/schemas.py (agent-scaffold's file) isn't
# written yet. Both functions here assume each row dict carries the fields a
# SmartBiz row needs, keyed the same as the Item model (SPEC.md §2):
#   id, name, price, category, product_category, description, imgbb_url
# and, for the default-category fallback, an optional "default_product_category"
# (falls back to "Other Food and Grocery", Shop's own default) since
# build_workbook's signature (rows, business_category) has no separate param
# for it. The row's "position" (1-based export row order) is read from an
# optional "row" key, defaulting to enumeration order.

def validate(rows: list[dict]) -> list[RowError]:
    """Check rows against the constraints the template's own validation enforces.

    Returns one RowError per violation found; an empty list means every row
    is safe to write into the workbook.
    """
    errors: list[RowError] = []
    for i, r in enumerate(rows):
        row_num = r.get("row", i + 2)
        item_id = str(r.get("id", ""))

        name = (r.get("name") or "").strip()
        if not name:
            errors.append(RowError(row_num, item_id, "name", "name is required"))
        elif len(name) > MAX_NAME:
            errors.append(RowError(
                row_num, item_id, "name",
                f"name is {len(name)} chars, exceeds the {MAX_NAME}-char limit",
            ))

        price = r.get("price")
        if price is None:
            errors.append(RowError(row_num, item_id, "price", "price (MRP) is required"))
        else:
            try:
                p = float(price)
                if p <= 0 or p > MAX_MRP:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(RowError(
                    row_num, item_id, "price", f"price {price!r} is not a valid MRP",
                ))
            else:
                # The template's own rule on column E caps MRP at 2 decimals.
                # Without this check a price like 10.999 passes validation and
                # is then silently rounded by build_workbook() - the sheet would
                # carry a number the admin never approved. Better to reject it
                # here and let a human decide.
                try:
                    exponent = Decimal(str(price)).as_tuple().exponent
                except (InvalidOperation, ValueError):
                    exponent = 0
                if isinstance(exponent, int) and exponent < -2:
                    errors.append(RowError(
                        row_num, item_id, "price",
                        f"price {price} has more than 2 decimal places",
                    ))

        # A row with no hosted image produces a catalogue entry with a blank
        # photo. That is exactly the kind of thing that has to be caught before
        # the upload, not discovered inside SmartBiz afterwards.
        if not (r.get("imgbb_url") or "").strip():
            errors.append(RowError(
                row_num, item_id, "imgbb_url",
                "no hosted image URL - run the hosting step, or exclude this item",
            ))

        default_cat = r.get("default_product_category") or "Other Food and Grocery"
        prod_cat = product_category_for(
            r.get("category", ""), r.get("product_category"), default_cat,
        )
        if prod_cat not in EXPORT_FOOD_CATEGORIES:
            errors.append(RowError(
                row_num, item_id, "product_category",
                f"'{prod_cat}' is not a legal SmartBiz product category",
            ))

        description = r.get("description") or ""
        if len(description) > MAX_DESC:
            errors.append(RowError(
                row_num, item_id, "description",
                f"description is {len(description)} chars, exceeds the {MAX_DESC}-char limit",
            ))

    return errors


def build_workbook(rows: list[dict], business_category: str) -> bytes:
    """Write `rows` into a copy of the SmartBiz template and return the .xlsx bytes.

    Loads templates/smartbiz_template.xlsx into memory and writes into that
    copy — never builds a fresh workbook, which would lose the template's 29
    data validations and break the SmartBiz import. Columns A (SKU ID) and B
    (Variant ID) are deliberately left empty; SmartBiz assigns them on import.
    """
    template_bytes = _template_full_path().read_bytes()
    wb = openpyxl.load_workbook(BytesIO(template_bytes))
    if SHEET not in wb.sheetnames:
        raise RuntimeError(f"template has no '{SHEET}' sheet (found: {wb.sheetnames})")
    ws = wb[SHEET]

    out_row = 2
    for r in rows:
        name = (r.get("name") or "")[:MAX_NAME]
        ws.cell(row=out_row, column=COL_NAME, value=name)

        price = r.get("price")
        try:
            price_val = round(float(price), 2) if price is not None else None
            if price_val is not None and (price_val <= 0 or price_val > MAX_MRP):
                price_val = None
        except (TypeError, ValueError):
            price_val = None
        ws.cell(row=out_row, column=COL_MRP, value=price_val)
        # Selling Price is OPTIONAL and means "the discounted price". Copying MRP
        # into it declares a zero-discount price the shop never agreed to, and the
        # original exporter deliberately left it blank. Only write it when the
        # item genuinely carries a distinct selling price <= MRP.
        selling = r.get("selling_price")
        try:
            selling_val = round(float(selling), 2) if selling is not None else None
        except (TypeError, ValueError):
            selling_val = None
        if selling_val is not None and price_val is not None and (
            selling_val < 0 or selling_val > price_val
        ):
            selling_val = None  # would trip the template's F<=E validation
        ws.cell(row=out_row, column=COL_SELLING, value=selling_val)

        ws.cell(row=out_row, column=COL_BUSINESS_CAT, value=business_category)

        default_cat = r.get("default_product_category") or "Other Food and Grocery"
        prod_cat = product_category_for(
            r.get("category", ""), r.get("product_category"), default_cat,
        )
        ws.cell(row=out_row, column=COL_PRODUCT_CAT, value=prod_cat)

        description = r.get("description") or r.get("category") or ""
        if description:
            ws.cell(row=out_row, column=COL_DESCRIPTION, value=description[:MAX_DESC])

        url = r.get("imgbb_url")
        if url:
            ws.cell(row=out_row, column=COL_IMAGE1, value=url)

        out_row += 1

    buf = BytesIO()
    wb.save(buf)
    wb.close()
    return buf.getvalue()
