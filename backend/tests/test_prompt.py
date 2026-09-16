"""Tests for app.engine.prompt: vessel selection, prop sanitising, prompt assembly.

These guard against the original tool's failure mode: hardcoding one reference
photo's look ("pale green background", "copper kadhai") into prose that lies
the moment a different reference image is uploaded.
"""
from app.engine import prompt as prompt_mod


# ---------------------------------------------------------------------------
# vessel_for
# ---------------------------------------------------------------------------

def test_vessel_for_curry_dish_gets_karahi_or_bowl():
    vessel = prompt_mod.vessel_for("Paneer Butter Masala", "Main Course")
    assert "karahi" in vessel.lower() or "bowl" in vessel.lower()


def test_vessel_for_fries_gets_basket_or_cone():
    vessel = prompt_mod.vessel_for("French Fries", "Sides")
    assert "basket" in vessel.lower() or "cone" in vessel.lower()


def test_vessel_for_shake_gets_glass():
    vessel = prompt_mod.vessel_for("Chocolate Shake", "Beverages")
    assert "glass" in vessel.lower()


def test_vessel_for_burger_gets_board():
    vessel = prompt_mod.vessel_for("Cheese Burger", "Fast Food")
    assert "board" in vessel.lower()


def test_vessel_for_biryani_gets_handi():
    vessel = prompt_mod.vessel_for("Chicken Biryani", "Rice")
    assert "handi" in vessel.lower()


def test_vessel_for_naan_gets_basket():
    vessel = prompt_mod.vessel_for("Butter Naan", "Breads")
    assert "basket" in vessel.lower()


def test_vessel_for_different_dishes_get_different_vessels():
    curry = prompt_mod.vessel_for("Paneer Butter Masala", "Main Course")
    burger = prompt_mod.vessel_for("Cheese Burger", "Fast Food")
    shake = prompt_mod.vessel_for("Chocolate Shake", "Beverages")
    assert len({curry, burger, shake}) == 3


# ---------------------------------------------------------------------------
# sanitize_props
# ---------------------------------------------------------------------------

def test_sanitize_props_drops_raw_paneer_behind_paneer_masala():
    cleaned = prompt_mod.sanitize_props(
        "Paneer Butter Masala", "Main Course", ["raw paneer cubes", "coriander leaves"],
    )
    assert not any("paneer" in p.lower() for p in cleaned)
    assert any("coriander" in p.lower() for p in cleaned)


def test_sanitize_props_drops_raw_chicken_behind_fried_chicken():
    cleaned = prompt_mod.sanitize_props(
        "Fried Chicken", "Starters", ["raw chicken pieces", "lemon wedge"],
    )
    assert not any("chicken" in p.lower() for p in cleaned)
    assert any("lemon" in p.lower() for p in cleaned)


def test_sanitize_props_keeps_fruit_behind_fruit_shake():
    cleaned = prompt_mod.sanitize_props(
        "Mango Shake", "Beverages", ["whole mangoes", "mint leaves"],
    )
    assert any("mango" in p.lower() for p in cleaned)


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------

STYLE = prompt_mod.StyleProfile(
    camera_angle="45-degree three-quarter view",
    lighting="bright directional key from upper left",
    surface="a textured light stone slab",
    background="a solid pale green seamless backdrop",
    colour_palette=["cream", "green", "gold"],
    mood="premium, earthy, appetising",
    vessel_in_reference="a copper kadhai with twin handles",
    props_in_reference=["scattered dry red chillies"],
)

SHOP = {"name": "Spice Route", "brand_archetype": "casual dining", "cuisine": "North Indian",
        "price_tier": "mid-range", "plating_style": "rustic", "prop_density": 1, "notes": ""}

ITEM = {"name": "Paneer Butter Masala", "category": "Main Course",
        "description": "Creamy tomato gravy", "concept_text": "", "suggested_vessel": None,
        "suggested_props": []}


def test_build_prompt_contains_dish_name_and_vessel():
    text = prompt_mod.build_prompt(STYLE, SHOP, ITEM, seed=0)
    assert "Paneer Butter Masala" in text
    vessel = prompt_mod.vessel_for(ITEM["name"], ITEM["category"], ITEM.get("suggested_vessel"))
    assert vessel in text


def test_build_prompt_contains_style_background_and_camera_angle():
    text = prompt_mod.build_prompt(STYLE, SHOP, ITEM, seed=0)
    assert STYLE["background"] in text
    assert STYLE["camera_angle"] in text


def test_build_prompt_warns_against_reusing_named_reference_vessel():
    text = prompt_mod.build_prompt(STYLE, SHOP, ITEM, seed=0)
    assert STYLE["vessel_in_reference"] in text
    assert "DO NOT reuse the serving vessel" in text


def test_build_prompt_no_instruction_when_reference_has_no_vessel():
    style_no_vessel = dict(STYLE)
    style_no_vessel["vessel_in_reference"] = "none"
    text = prompt_mod.build_prompt(style_no_vessel, SHOP, ITEM, seed=0)
    assert "DO NOT reuse the serving vessel" not in text


def test_build_prompt_does_not_hardcode_old_tool_leftovers():
    """Regression: the original tool baked one reference photo's look into
    every prompt ('pale green background', 'copper kadhai'). When the derived
    style profile doesn't mention those phrases, they must not appear."""
    neutral_style = prompt_mod.NEUTRAL_STYLE
    text = prompt_mod.build_prompt(neutral_style, SHOP, ITEM, seed=0)
    assert "pale green" not in text.lower()
    assert "kadhai" not in text.lower()


# ---------------------------------------------------------------------------
# fallback_prompt
# ---------------------------------------------------------------------------

def test_fallback_prompt_gets_progressively_shorter():
    p0 = prompt_mod.fallback_prompt("Paneer Butter Masala", "desc", "Main Course", 0, STYLE)
    p1 = prompt_mod.fallback_prompt("Paneer Butter Masala", "desc", "Main Course", 1, STYLE)
    p2 = prompt_mod.fallback_prompt("Paneer Butter Masala", "desc", "Main Course", 2, STYLE)
    assert len(p0) > len(p1) > len(p2)


def test_fallback_prompt_last_attempt_is_plain_and_style_free():
    p2 = prompt_mod.fallback_prompt("Paneer Butter Masala", "desc", "Main Course", 2, STYLE)
    # The final rung deliberately drops all derived-style detail.
    assert STYLE["camera_angle"] not in p2
    assert STYLE["background"] not in p2
