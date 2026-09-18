/// screens/Catalog.tsx — final grid of generated dishes (SPEC.md §9): inline
/// edit, per-image download/regenerate, and the export-to-SmartBiz panel.
import { useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  shopImagesZipUrl,
  useCreateJob,
  useItems,
  usePurgeShopImages,
  useRegenerateItem,
  useShopStorage,
  useUpdateItem,
} from "../api/hooks";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { Spinner } from "../components/Spinner";
import { useToast } from "../components/Toast";
import { CatalogCard } from "./catalog/CatalogCard";
import { ExportPanel } from "./catalog/ExportPanel";
import { setStoredJobId } from "./generate/jobStorage";
import { formatBytes } from "./settings/StorageSection";

const SHOWN_STATUSES = new Set(["generated", "hosted"]);

export default function Catalog() {
  const { id: shopId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();

  const itemsQ = useItems(shopId, {});
  const updateM = useUpdateItem(shopId ?? "");
  const regenM = useRegenerateItem(shopId ?? "");
  const createJobM = useCreateJob(shopId ?? "");
  const shopStorageQ = useShopStorage(shopId);
  const purgeM = usePurgeShopImages();

  const [highlighted, setHighlighted] = useState<string | null>(null);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const allItems = itemsQ.data?.items ?? [];
  const items = useMemo(
    () =>
      allItems
        .filter((i) => SHOWN_STATUSES.has(i.status))
        .sort((a, b) => a.position - b.position),
    [allItems],
  );
  const excludedCount = allItems.length - items.length;

  function scrollToItem(itemId: string) {
    setHighlighted(itemId);
    cardRefs.current[itemId]?.scrollIntoView({ behavior: "smooth", block: "center" });
    if (highlightTimer.current) clearTimeout(highlightTimer.current);
    highlightTimer.current = setTimeout(() => setHighlighted(null), 2500);
  }

  async function handleRegenerate(itemId: string) {
    await regenM.mutateAsync(itemId);
    try {
      const job = await createJobM.mutateAsync("generate");
      if (shopId) setStoredJobId(shopId, job.id);
      toast.show("Requeued — opening the generate run", "success");
      navigate(`/shops/${shopId}/generate?job=${job.id}`);
    } catch {
      // Most likely a job is already running (409 conflict); the item was
      // still requeued, so send them to whatever run is already tracked.
      toast.show("Item requeued. A generation run is already active — opening it.", "info");
      navigate(`/shops/${shopId}/generate`);
    }
  }

  async function handleFreeUpSpace() {
    if (!shopId) return;
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

  if (itemsQ.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner size={24} />
      </div>
    );
  }

  if (itemsQ.isError) {
    return (
      <div className="p-6">
        <EmptyState
          title="Could not load the catalog"
          action={
            <Button size="sm" onClick={() => void itemsQ.refetch()}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="p-6">
        <EmptyState
          title="No generated dishes yet"
          description="Run a generation job first."
          action={
            <Link to={`/shops/${shopId}/generate`}>
              <Button size="sm">Go to generate</Button>
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-base-100">Catalog</h1>
          <p className="text-xs text-base-400">
            {items.length} dish(es) ready
            {excludedCount > 0 && ` · ${excludedCount} skipped/failed hidden from this grid`}
            {shopStorageQ.data && ` · ${formatBytes(shopStorageQ.data.total_bytes)} stored`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {shopId && (
            <a href={shopImagesZipUrl(shopId)}>
              <Button size="sm" variant="secondary">
                Download all images
              </Button>
            </a>
          )}
          <Button size="sm" variant="secondary" loading={purgeM.isPending} onClick={handleFreeUpSpace}>
            Free up space
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {items.map((item) => (
          <div key={item.id} ref={(el) => (cardRefs.current[item.id] = el)}>
            <CatalogCard
              item={item}
              highlighted={highlighted === item.id}
              onSave={(payload) => updateM.mutateAsync({ id: item.id, payload }).then(() => undefined)}
              onRegenerate={() => void handleRegenerate(item.id)}
              regenerating={regenM.isPending && regenM.variables === item.id}
            />
          </div>
        ))}
      </div>

      <ExportPanel shopId={shopId} items={items} onJumpToItem={scrollToItem} />
    </div>
  );
}
