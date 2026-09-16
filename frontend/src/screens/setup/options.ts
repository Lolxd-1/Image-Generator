/// screens/setup/options.ts — seed option lists for the 7 shop context
/// metrics (SPEC.md §2 Shop model: brand_archetype, cuisine, price_tier,
/// plating_style, lighting_mood, background_setting, prop_density, notes).
/// Every select also carries a free-text "Other" fallback (see OtherSelect),
/// so these lists only need to cover the common cases.
export const BRAND_ARCHETYPE_OPTIONS = [
  "QSR chain (KFC-style)",
  "Casual dining",
  "Fine dining",
  "Cloud kitchen",
  "Local neighbourhood eatery",
  "Bakery / cafe",
  "Food truck / stall",
];

export const CUISINE_OPTIONS = [
  "North Indian",
  "South Indian",
  "Chinese / Indo-Chinese",
  "Continental",
  "Italian",
  "Mexican",
  "Bakery & desserts",
  "Multi-cuisine",
];

export const PRICE_TIER_OPTIONS = ["Budget", "Mid-range", "Premium", "Luxury"];

export const PLATING_STYLE_OPTIONS = [
  "Clean minimal branded packaging",
  "Rustic generous homestyle",
  "Elegant fine-dining plating",
  "Street-food casual",
];

export const LIGHTING_MOOD_OPTIONS = [
  "Bright and airy",
  "Warm and cozy",
  "Moody and dramatic",
  "Studio-clean",
  "Natural daylight",
];

export const BACKGROUND_SETTING_OPTIONS = [
  "Restaurant table setting",
  "Neutral studio backdrop",
  "Wooden rustic surface",
  "Marble / premium surface",
  "Outdoor / al fresco",
];

/** Labels for the prop_density 0-3 slider. */
export const PROP_DENSITY_LABELS = ["None", "Sparse", "Moderate", "Rich"];
