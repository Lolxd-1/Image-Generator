/// screens/Shops.tsx — landing screen: shop grid with a resume-where-you-
/// left-off primary action per shop, new-shop creation, and archive/
/// unarchive.
import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, patch } from "../api/client";
import { qk, useCreateShop, useDeleteShop, useShops } from "../api/hooks";
import type { Shop, ShopSummary, UpdateShopPayload } from "../api/types";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { Card, CardHeader, CardTitle } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { Input } from "../components/Input";
import { Modal } from "../components/Modal";
import { Spinner } from "../components/Spinner";
import { useToast } from "../components/Toast";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function progressSummary(shop: ShopSummary): string {
  if (shop.total_items === 0) return "No items extracted yet";
  const c = shop.item_counts;
  const approved = c.approved ?? 0;
  const needsReview = (c.needs_review ?? 0) + (c.new ?? 0) + (c.awaiting_ref ?? 0);
  const generated = (c.generated ?? 0) + (c.hosted ?? 0);
  return `${approved} approved / ${needsReview} need review / ${generated} generated`;
}

/** Where the primary action on a card should take the admin next. */
function resumeFor(shop: ShopSummary): { label: string; path: string } {
  const base = `/shops/${shop.id}`;
  if (shop.total_items === 0) return { label: "Continue setup", path: `${base}/setup` };
  const c = shop.item_counts;
  const pending = (c.new ?? 0) + (c.needs_review ?? 0) + (c.awaiting_ref ?? 0);
  if (pending > 0) return { label: "Review items", path: `${base}/review` };
  if ((c.approved ?? 0) > 0) return { label: "Generate images", path: `${base}/generate` };
  if ((c.generated ?? 0) + (c.hosted ?? 0) > 0) {
    return { label: "View catalog", path: `${base}/catalog` };
  }
  return { label: "Continue setup", path: `${base}/setup` };
}

// SPEC-GAP: SPEC.md's API contract (§6) lists no archive endpoint, and
// hooks.ts has no archive/unarchive mutation. Shop and ShopSummary both
// already model `archived_at`, so this reuses the general-purpose
// PATCH /api/shops/{id} "partial context update" route with that field
// rather than inventing a new endpoint.
function useSetArchived() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, archived }: { id: string; archived: boolean }) =>
      patch<Shop>(`/shops/${id}`, {
        archived_at: archived ? new Date().toISOString() : null,
      } as UpdateShopPayload & { archived_at: string | null }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.shops });
    },
  });
}

function ShopCard({
  shop,
  archiving,
  onArchiveToggle,
  onDelete,
}: {
  shop: ShopSummary;
  archiving: boolean;
  onArchiveToggle: (shop: ShopSummary) => void;
  onDelete: (shop: ShopSummary) => void;
}) {
  const navigate = useNavigate();
  const resume = resumeFor(shop);
  const archived = Boolean(shop.archived_at);

  return (
    <Card className={archived ? "opacity-60" : undefined}>
      <CardHeader>
        <CardTitle>{shop.name}</CardTitle>
        {archived && <Badge tone="neutral">Archived</Badge>}
      </CardHeader>
      <p className="text-xs text-base-400">Created {formatDate(shop.created_at)}</p>
      <p className="mt-2 text-sm text-base-200">{progressSummary(shop)}</p>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={archived} onClick={() => navigate(resume.path)}>
          {resume.label}
        </Button>
        <Button size="sm" variant="ghost" loading={archiving} onClick={() => onArchiveToggle(shop)}>
          {archived ? "Unarchive" : "Archive"}
        </Button>
        <Button size="sm" variant="danger" onClick={() => onDelete(shop)}>
          Delete
        </Button>
      </div>
    </Card>
  );
}

/** Irreversible: requires the operator to type the shop name to enable the button. */
function DeleteShopModal({
  shop,
  open,
  onClose,
}: {
  shop: ShopSummary | null;
  open: boolean;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const deleteShop = useDeleteShop();
  const toast = useToast();

  useEffect(() => {
    if (open) setTyped("");
  }, [open]);

  if (!shop) return null;
  const matches = typed.trim() === shop.name;

  async function handleDelete() {
    try {
      await deleteShop.mutateAsync(shop!.id);
      toast.show(`Deleted "${shop!.name}"`, "success");
      onClose();
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not delete the shop.", "error");
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={`Delete "${shop.name}"?`}>
      <p className="mb-3 text-sm text-base-300">
        This permanently deletes the shop, its catalog, and all stored images. This cannot be
        undone. Type <span className="font-semibold text-base-100">{shop.name}</span> to confirm.
      </p>
      <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="danger" disabled={!matches} loading={deleteShop.isPending} onClick={handleDelete}>
          Delete permanently
        </Button>
      </div>
    </Modal>
  );
}

function NewShopModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const createShop = useCreateShop();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const shop = await createShop.mutateAsync({ name: name.trim() });
      setName("");
      onClose();
      navigate(`/shops/${shop.id}/setup`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create shop.");
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="New shop">
      <form className="flex flex-col gap-3" onSubmit={onSubmit}>
        <Input
          label="Shop name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          required
        />
        {error && <p className="text-xs text-danger-400">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={createShop.isPending} disabled={!name.trim()}>
            Create
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default function Shops() {
  const { data: shops, isLoading, isError, error } = useShops();
  const [showArchived, setShowArchived] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [archivingId, setArchivingId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ShopSummary | null>(null);
  const setArchived = useSetArchived();
  const toast = useToast();

  const visible = useMemo(() => {
    if (!shops) return [];
    return showArchived ? shops : shops.filter((s) => !s.archived_at);
  }, [shops, showArchived]);

  async function handleArchiveToggle(shop: ShopSummary) {
    const archived = Boolean(shop.archived_at);
    if (!archived && !window.confirm(`Archive "${shop.name}"? You can unarchive it later.`)) {
      return;
    }
    setArchivingId(shop.id);
    try {
      await setArchived.mutateAsync({ id: shop.id, archived: !archived });
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not update the shop.", "error");
    } finally {
      setArchivingId(null);
    }
  }

  const hasAnyShops = Boolean(shops && shops.length > 0);

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-base-100">Shops</h1>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-base-400">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
            />
            Show archived
          </label>
          <Link to="/settings">
            <Button size="sm" variant="secondary">
              Settings
            </Button>
          </Link>
          <Button size="sm" onClick={() => setModalOpen(true)}>
            New shop
          </Button>
        </div>
      </div>

      {isLoading && (
        <div className="flex justify-center py-16">
          <Spinner size={24} />
        </div>
      )}

      {isError && (
        <EmptyState
          title="Could not load shops"
          description={error instanceof ApiError ? error.message : "Please refresh and try again."}
        />
      )}

      {!isLoading && !isError && visible.length === 0 && (
        <EmptyState
          title={hasAnyShops ? "No archived shops" : "No shops yet"}
          description={
            hasAnyShops
              ? 'Every shop is active. Turn off "Show archived" to see them.'
              : "Create your first shop to upload a menu and start generating catalog-ready dish photos."
          }
          action={
            !hasAnyShops ? (
              <Button size="sm" onClick={() => setModalOpen(true)}>
                New shop
              </Button>
            ) : undefined
          }
        />
      )}

      {!isLoading && !isError && visible.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((shop) => (
            <ShopCard
              key={shop.id}
              shop={shop}
              archiving={archivingId === shop.id}
              onArchiveToggle={handleArchiveToggle}
              onDelete={setDeleteTarget}
            />
          ))}
        </div>
      )}

      <NewShopModal open={modalOpen} onClose={() => setModalOpen(false)} />
      <DeleteShopModal shop={deleteTarget} open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)} />
    </div>
  );
}
