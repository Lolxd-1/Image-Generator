/// screens/catalog/exportCategories.ts — the legal column-H values for the
/// SmartBiz food export, copied verbatim from SPEC.md §4
/// (app/engine/export.py EXPORT_FOOD_CATEGORIES). Backend owns the real
/// constant; this is a UI-only copy for the product_category <select>.
export const EXPORT_FOOD_CATEGORIES = [
  "Fruits & Vegetables",
  "Food grains, Oil & Masala",
  "Bakery",
  "Dairy",
  "Beverages",
  "Eggs, Meat & Seafood",
  "Namkeen, Snacks & Biscuits",
  "Health food",
  "Instant Food",
  "Chocolates, desserts and icecream",
  "Mithai (Indian Sweets)",
  "Baby food",
  "Gourmet Food",
  "Pet food",
  "Other Food and Grocery",
] as const;
