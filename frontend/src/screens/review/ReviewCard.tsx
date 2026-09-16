/// screens/review/ReviewCard.tsx — one dish's review card: the AI's concept
/// text is the whole point of Review.tsx (SPEC.md §9) — the admin approves
/// the *interpretation* before any image-generation quota is spent.
import { useState } from "react";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { ConfidenceBar } from "../../components/ConfidenceBar";
import { DropZone } from "../../components/DropZone";
import { Modal } from "../../components/Modal";
import { StatusPill } from "../../components/StatusPill";
import { Textarea } from "../../components/Textarea";
import { cn } from "../../lib/cn";
import type { Item } from "../../api/types";

export interface ReviewCardProps {
  item: Item;
  selected: boolean;
  onSelect: () => void;
  onApprove: () => void;
  onSkip: () => void;
  onSaveConcept: (text: string) => Promise<void>;
  onUploadReference: (file: File) => Promise<void>;
  busy?: boolean;
}

export function ReviewCard({
  item,
  selected,
  onSelect,
  onApprove,
  onSkip,
  onSaveConcept,
  onUploadReference,
  busy,
}: ReviewCardProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.concept_text ?? "");
  const [saving, setSaving] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await onSaveConcept(draft);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  async function handleFile(files: File[]) {
    const file = files[0];
    if (!file) return;
    setUploading(true);
    try {
      await onUploadReference(file);
      setUploadOpen(false);
    } finally {
      setUploading(false);
    }
  }

  return (
    <Card
      id={`review-item-${item.id}`}
      onClick={onSelect}
      className={cn(
        "cursor-pointer transition-colors",
        selected ? "border-accent-500 ring-1 ring-accent-500/40" : "hover:border-base-500",
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-base-100">{item.name}</h3>
            <StatusPill status={item.status} />
          </div>
          <p className="mt-0.5 text-xs text-base-400">
            {item.category}
            {item.price !== null && ` · Rs ${item.price.toFixed(2)}`}
          </p>
        </div>
        <ConfidenceBar value={item.confidence} />
      </div>

      {item.confidence_reason && (
        <p className="mb-2 text-xs italic text-base-400">{item.confidence_reason}</p>
      )}

      {editing ? (
        <div className="mb-3 flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={4}
            autoFocus
          />
          <div className="flex gap-2">
            <Button size="sm" onClick={handleSave} loading={saving}>
              Save concept
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setDraft(item.concept_text ?? "");
                setEditing(false);
              }}
              disabled={saving}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <p className="mb-3 whitespace-pre-wrap text-sm text-base-200">
          {item.concept_text || (
            <span className="italic text-base-500">No concept text yet.</span>
          )}
        </p>
      )}

      {item.manual_ref_image_id && (
        <Badge tone="accent" className="mb-2">
          Own reference uploaded
        </Badge>
      )}

      <div
        className="flex flex-wrap gap-2"
        onClick={(e) => e.stopPropagation()}
      >
        <Button size="sm" onClick={onApprove} disabled={busy}>
          Approve concept
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => setEditing((v) => !v)}
          disabled={busy}
        >
          Edit concept
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => setUploadOpen(true)}
          disabled={busy}
        >
          Upload own reference
        </Button>
        <Button size="sm" variant="danger" onClick={onSkip} disabled={busy}>
          Skip item
        </Button>
      </div>

      <Modal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        title={`Reference image for ${item.name}`}
      >
        <DropZone
          accept="image/*"
          multiple={false}
          onFiles={handleFile}
          disabled={uploading}
          label={uploading ? "Uploading..." : "Drop a reference photo, or click to browse"}
        />
      </Modal>
    </Card>
  );
}
