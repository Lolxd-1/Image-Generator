/// screens/catalog/CatalogCard.tsx — one generated dish in the final grid:
/// image, editable fields, per-image download/regenerate.
import { useState } from "react";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Input } from "../../components/Input";
import { Modal } from "../../components/Modal";
import { Select } from "../../components/Select";
import { Textarea } from "../../components/Textarea";
import { cn } from "../../lib/cn";
import { imageUrl } from "../../api/hooks";
import type { Item, UpdateItemPayload } from "../../api/types";
import { EXPORT_FOOD_CATEGORIES } from "./exportCategories";

const CATEGORY_OPTIONS = EXPORT_FOOD_CATEGORIES.map((c) => ({ value: c, label: c }));

export interface CatalogCardProps {
  item: Item;
  highlighted?: boolean;
  onSave: (payload: UpdateItemPayload) => Promise<void>;
  onRegenerate: () => void;
  regenerating?: boolean;
}

export function CatalogCard({
  item,
  highlighted,
  onSave,
  onRegenerate,
  regenerating,
}: CatalogCardProps) {
  const [editing, setEditing] = useState(false);
  const [confirmRegen, setConfirmRegen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({
    name: item.name,
    price: item.price !== null ? String(item.price) : "",
    description: item.description,
    product_category: item.product_category ?? "",
  });

  function startEdit() {
    setDraft({
      name: item.name,
      price: item.price !== null ? String(item.price) : "",
      description: item.description,
      product_category: item.product_category ?? "",
    });
    setEditing(true);
  }

  async function handleSave() {
    setSaving(true);
    try {
      await onSave({
        name: draft.name,
        price: draft.price === "" ? null : Number(draft.price),
        description: draft.description,
        product_category: draft.product_category || null,
      });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card
      className={cn(
        "flex flex-col gap-2 transition-colors",
        highlighted && "border-warn-500 ring-2 ring-warn-500/50",
      )}
    >
      {item.image_id ? (
        <img
          src={imageUrl(item.image_id)}
          alt={item.name}
          className="h-40 w-full rounded-md border border-base-700 object-cover"
          loading="lazy"
        />
      ) : (
        <div className="flex h-40 w-full items-center justify-center rounded-md border border-base-700 bg-base-800 text-xs text-base-400">
          Image removed to free space
        </div>
      )}

      {editing ? (
        <div className="flex flex-col gap-2">
          <Input
            label="Name"
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          />
          <Input
            label="Price"
            type="number"
            step="0.01"
            value={draft.price}
            onChange={(e) => setDraft((d) => ({ ...d, price: e.target.value }))}
          />
          <Select
            label="Product category (SmartBiz)"
            options={CATEGORY_OPTIONS}
            placeholder="Choose category"
            value={draft.product_category}
            onChange={(e) => setDraft((d) => ({ ...d, product_category: e.target.value }))}
          />
          <Textarea
            label="Description"
            rows={3}
            value={draft.description}
            onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
          />
          <div className="flex gap-2">
            <Button size="sm" onClick={handleSave} loading={saving}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={saving}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          <h3 className="truncate text-sm font-semibold text-base-100">{item.name}</h3>
          <p className="text-xs text-base-400">
            {item.category}
            {item.price !== null && ` · Rs ${item.price.toFixed(2)}`}
          </p>
          <p className="text-xs text-base-500">
            SmartBiz: {item.product_category ?? <span className="italic">unset</span>}
          </p>
          {item.description && (
            <p className="line-clamp-2 text-xs text-base-400">{item.description}</p>
          )}
        </div>
      )}

      {!editing && (
        <div className="mt-auto flex flex-wrap gap-2 pt-1">
          <Button size="sm" variant="secondary" onClick={startEdit}>
            Edit
          </Button>
          {item.image_id && (
            <a href={imageUrl(item.image_id, true)} download>
              <Button size="sm" variant="secondary">
                Download
              </Button>
            </a>
          )}
          <Button
            size="sm"
            variant="danger"
            onClick={() => setConfirmRegen(true)}
            loading={regenerating}
          >
            Regenerate
          </Button>
        </div>
      )}

      <Modal
        open={confirmRegen}
        onClose={() => setConfirmRegen(false)}
        title="Regenerate this image?"
      >
        <p className="mb-4 text-sm text-base-300">
          This replaces the current image and spends generation quota. Open the Generate
          screen afterward if a run isn't already active.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmRegen(false)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              setConfirmRegen(false);
              onRegenerate();
            }}
          >
            Regenerate
          </Button>
        </div>
      </Modal>
    </Card>
  );
}
