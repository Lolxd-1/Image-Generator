/// screens/setup/ContextForm.tsx — the 7 shop context metrics (SPEC.md §2
/// Shop model) with debounced autosave via PATCH /api/shops/{id}.
import { useEffect, useRef, useState } from "react";
import { useUpdateShop } from "../../api/hooks";
import type { Shop, UpdateShopPayload } from "../../api/types";
import { Card, CardHeader, CardTitle } from "../../components/Card";
import { Textarea } from "../../components/Textarea";
import {
  BACKGROUND_SETTING_OPTIONS,
  BRAND_ARCHETYPE_OPTIONS,
  CUISINE_OPTIONS,
  LIGHTING_MOOD_OPTIONS,
  PLATING_STYLE_OPTIONS,
  PRICE_TIER_OPTIONS,
  PROP_DENSITY_LABELS,
} from "./options";
import { OtherSelect } from "./OtherSelect";

type ContextFields = Pick<
  UpdateShopPayload,
  | "brand_archetype"
  | "cuisine"
  | "price_tier"
  | "plating_style"
  | "lighting_mood"
  | "background_setting"
  | "prop_density"
  | "notes"
>;

const DEBOUNCE_MS = 900;

function fieldsFrom(shop: Shop): ContextFields {
  return {
    brand_archetype: shop.brand_archetype,
    cuisine: shop.cuisine,
    price_tier: shop.price_tier,
    plating_style: shop.plating_style,
    lighting_mood: shop.lighting_mood,
    background_setting: shop.background_setting,
    prop_density: shop.prop_density,
    notes: shop.notes,
  };
}

export function ContextForm({ shop }: { shop: Shop }) {
  const shopId = shop.id;
  const [fields, setFields] = useState<ContextFields>(() => fieldsFrom(shop));
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const updateShop = useUpdateShop(shopId);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Re-seed local state when navigating between shops.
  useEffect(() => {
    setFields(fieldsFrom(shop));
    setSaveState("idle");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shopId]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  function patchField<K extends keyof ContextFields>(key: K, value: ContextFields[K]) {
    const next = { ...fields, [key]: value };
    setFields(next);
    setSaveState("saving");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      updateShop.mutate(next, {
        onSuccess: () => {
          setSaveState("saved");
          setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 2000);
        },
        onError: () => setSaveState("idle"),
      });
    }, DEBOUNCE_MS);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Shop context</CardTitle>
        <span className="text-xs text-base-400">
          {saveState === "saving" ? "Saving…" : saveState === "saved" ? "Saved" : ""}
        </span>
      </CardHeader>
      <p className="mb-3 text-xs text-base-400">
        These describe your shop's visual identity to the AI — e.g. a "QSR
        chain (KFC-style), premium, clean minimal branded packaging" reads
        very differently from a "local neighbourhood eatery, budget, rustic
        generous homestyle".
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <OtherSelect
          label="Brand archetype"
          hint="What kind of place is this?"
          options={BRAND_ARCHETYPE_OPTIONS}
          value={fields.brand_archetype ?? null}
          onChange={(v) => patchField("brand_archetype", v)}
        />
        <OtherSelect
          label="Cuisine"
          hint="Main cuisine served."
          options={CUISINE_OPTIONS}
          value={fields.cuisine ?? null}
          onChange={(v) => patchField("cuisine", v)}
        />
        <OtherSelect
          label="Price tier"
          hint="Positioning, not exact prices."
          options={PRICE_TIER_OPTIONS}
          value={fields.price_tier ?? null}
          onChange={(v) => patchField("price_tier", v)}
        />
        <OtherSelect
          label="Plating style"
          hint="How dishes are typically presented."
          options={PLATING_STYLE_OPTIONS}
          value={fields.plating_style ?? null}
          onChange={(v) => patchField("plating_style", v)}
        />
        <OtherSelect
          label="Lighting mood"
          hint="The feel of the light in generated photos."
          options={LIGHTING_MOOD_OPTIONS}
          value={fields.lighting_mood ?? null}
          onChange={(v) => patchField("lighting_mood", v)}
        />
        <OtherSelect
          label="Background setting"
          hint="What's behind or under the dish."
          options={BACKGROUND_SETTING_OPTIONS}
          value={fields.background_setting ?? null}
          onChange={(v) => patchField("background_setting", v)}
        />
      </div>

      <div className="mt-4 flex flex-col gap-1.5">
        <span className="text-xs font-medium text-base-300">Prop density</span>
        <input
          type="range"
          min={0}
          max={3}
          step={1}
          value={fields.prop_density ?? 1}
          onChange={(e) => patchField("prop_density", Number(e.target.value))}
          className="w-full accent-accent-500"
        />
        <div className="flex justify-between text-[11px] text-base-400">
          {PROP_DENSITY_LABELS.map((l) => (
            <span key={l}>{l}</span>
          ))}
        </div>
        <span className="text-xs text-base-400">
          How many extra props (cutlery, garnish, napkins) should surround the dish.
        </span>
      </div>

      <Textarea
        className="mt-4"
        label="Notes"
        hint="Anything else the AI should know — brand colours, things to avoid, etc."
        value={fields.notes ?? ""}
        onChange={(e) => patchField("notes", e.target.value || null)}
        rows={3}
      />
    </Card>
  );
}
