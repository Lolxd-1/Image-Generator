/// screens/settings/StorageSection.tsx — the 1 GB storage budget bar, a
/// per-shop breakdown, and the download / free-up-space / delete-catalog
/// actions (T07).
import { useState } from "react";
import { ApiError } from "../../api/client";
import {
  shopImagesZipUrl,
  useDeleteShop,
  usePurgeShopImages,
  useStorageUsage,
} from "../../api/hooks";
import type { ShopStorage } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardHeader, CardTitle } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { Input } from "../../components/Input";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { useToast } from "../../components/Toast";

/** "1.4 GB" / "812 MB" / "64 KB" / "0 B" — one decimal place above MB only. */
export function formatBytes(n: number): string {
  if (n <= 0) return "0 B";
  const KB = 1024;
  const MB = KB * 1024;
  const GB = MB * 1024;
  if (n < KB) return `${Math.round(n)} B`;
  if (n < MB) return `${Math.round(n / KB)} KB`;
  if (n < GB) return `${Math.round(n / MB)} MB`;
  return `${(n / GB).toFixed(1)} GB`;
}

function UsageBar({ totalBytes, budgetBytes }: { totalBytes: number; budgetBytes: number }) {
  const pct = budgetBytes > 0 ? Math.min(100, (totalBytes / budgetBytes) * 100) : 0;
  const tone = pct > 90 ? "bg-danger-500" : pct > 75 ? "bg-warn-500" : "bg-accent-600";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs text-base-400">
        <span>
          {formatBytes(totalBytes)} of {formatBytes(budgetBytes)} used
        </span>
        <span>{Math.round(pct)}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-base-800">
        <div className={`h-full rounded-full ${tone} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function PurgeButton({ shopId }: { shopId: string }) {
  const purgeM = usePurgeShopImages();
  const toast = useToast();

  async function handlePurge() {
    if (
      !window.confirm(
        "Free up space by deleting this shop's generated images from storage? Download them first if you need them — this cannot be undone.",
      )
    ) {
      return;
    }
    try {
      const result = await purgeM.mutateAsync(shopId);
      toast.show(`Freed ${formatBytes(result.bytes_freed)}`, "success");
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not free up space.", "error");
    }
  }

  return (
    <Button size="sm" variant="secondary" loading={purgeM.isPending} onClick={handlePurge}>
      Free up space
    </Button>
  );
}

function DeleteCatalogModal({
  shop,
  open,
  onClose,
}: {
  shop: ShopStorage;
  open: boolean;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const deleteShop = useDeleteShop();
  const toast = useToast();
  const matches = typed.trim() === shop.shop_name;

  function close() {
    setTyped("");
    onClose();
  }

  async function handleDelete() {
    try {
      await deleteShop.mutateAsync(shop.shop_id);
      toast.show(`Deleted "${shop.shop_name}"`, "success");
      close();
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not delete the shop.", "error");
    }
  }

  return (
    <Modal open={open} onClose={close} title={`Delete "${shop.shop_name}"?`}>
      <p className="mb-3 text-sm text-base-300">
        This permanently deletes the shop, its catalog, and all stored images. Type{" "}
        <span className="font-semibold text-base-100">{shop.shop_name}</span> to confirm.
      </p>
      <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={close}>
          Cancel
        </Button>
        <Button variant="danger" disabled={!matches} loading={deleteShop.isPending} onClick={handleDelete}>
          Delete permanently
        </Button>
      </div>
    </Modal>
  );
}

function ShopStorageRow({ shop }: { shop: ShopStorage }) {
  const [deleteOpen, setDeleteOpen] = useState(false);
  return (
    <div className="flex flex-col gap-2 border-b border-base-800 py-3 last:border-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-base-100">{shop.shop_name}</p>
          <p className="text-xs text-base-400">
            {formatBytes(shop.total_bytes)} total · {shop.dish_count} dish image
            {shop.dish_count === 1 ? "" : "s"}
          </p>
          <p className="text-xs text-base-500">
            Dish {formatBytes(shop.dish_bytes)} · Menu {shop.menu_count} (not counted) · Reference{" "}
            {formatBytes(shop.reference_bytes)} · Export {shop.export_count} (not counted)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <a href={shopImagesZipUrl(shop.shop_id)}>
            <Button size="sm" variant="secondary">
              Download images
            </Button>
          </a>
          <PurgeButton shopId={shop.shop_id} />
          <Button size="sm" variant="danger" onClick={() => setDeleteOpen(true)}>
            Delete catalog
          </Button>
        </div>
      </div>
      <DeleteCatalogModal shop={shop} open={deleteOpen} onClose={() => setDeleteOpen(false)} />
    </div>
  );
}

export function StorageSection() {
  const storageQ = useStorageUsage();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Storage</CardTitle>
      </CardHeader>
      {storageQ.isLoading ? (
        <div className="flex justify-center py-6">
          <Spinner size={20} />
        </div>
      ) : storageQ.isError ? (
        <EmptyState title="Could not load storage usage" />
      ) : storageQ.data ? (
        <div className="flex flex-col gap-4">
          <UsageBar totalBytes={storageQ.data.total_bytes} budgetBytes={storageQ.data.budget_bytes} />
          <p className="text-xs text-base-500">
            Menu photos and exports are counted but not sized.
          </p>
          {storageQ.data.shops.length === 0 ? (
            <EmptyState
              title="No shops yet"
              description="Storage usage will appear here once a shop has images."
            />
          ) : (
            <div className="flex flex-col">
              {[...storageQ.data.shops]
                .sort((a, b) => b.total_bytes - a.total_bytes)
                .map((shop) => (
                  <ShopStorageRow key={shop.shop_id} shop={shop} />
                ))}
            </div>
          )}
        </div>
      ) : null}
    </Card>
  );
}
