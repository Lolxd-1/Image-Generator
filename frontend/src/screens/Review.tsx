/// screens/Review.tsx — approve/edit/skip AI-classified items before any
/// image-generation quota is spent (SPEC.md §9). Two tabs bucket items by
/// ItemStatus: "needs_review" (confidence < 90, plus "awaiting_ref") is what
/// still needs a human decision; "approved" already cleared for generation
/// (auto-approved at classify time, or approved here).
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useApproveItem,
  useCreateJob,
  useHoldItem,
  useItems,
  useShop,
  useSkipItem,
  useUpdateItem,
  useUploadItemReference,
} from "../api/hooks";
import type { Item } from "../api/types";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { Spinner } from "../components/Spinner";
import { useToast } from "../components/Toast";
import { setStoredJobId } from "./generate/jobStorage";
import { BulkApproveModal } from "./review/BulkApproveModal";
import { ReviewCard } from "./review/ReviewCard";
import { ReviewHeader } from "./review/ReviewHeader";
import { ReviewTabs } from "./review/ReviewTabs";
import type { Tab } from "./review/ReviewTabs";
import { useReviewShortcuts } from "./review/useReviewShortcuts";

export default function Review() {
  const { id: shopId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();

  const shopQ = useShop(shopId);
  const needsReviewQ = useItems(shopId, { status: "needs_review" });
  const awaitingRefQ = useItems(shopId, { status: "awaiting_ref" });
  const approvedQ = useItems(shopId, { status: "approved" });

  const approveM = useApproveItem(shopId ?? "");
  const holdM = useHoldItem(shopId ?? "");
  const skipM = useSkipItem(shopId ?? "");
  const updateM = useUpdateItem(shopId ?? "");
  const uploadRefM = useUploadItemReference(shopId ?? "");
  const createJobM = useCreateJob(shopId ?? "");

  const [tab, setTab] = useState<Tab>("needs_review");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [bulkConfirmOpen, setBulkConfirmOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const needsReview = useMemo<Item[]>(() => {
    const combined = [
      ...(needsReviewQ.data?.items ?? []),
      ...(awaitingRefQ.data?.items ?? []),
    ];
    return combined.sort((a, b) => a.position - b.position);
  }, [needsReviewQ.data, awaitingRefQ.data]);
  const needsReviewTotal =
    (needsReviewQ.data?.total ?? 0) + (awaitingRefQ.data?.total ?? 0);

  const approved = approvedQ.data?.items ?? [];
  const approvedTotal = approvedQ.data?.total ?? approved.length;

  const list = tab === "needs_review" ? needsReview : approved;

  useEffect(() => {
    setSelectedIndex((i) => Math.min(i, Math.max(0, list.length - 1)));
  }, [list.length, tab]);

  useReviewShortcuts({
    suspended: Boolean(editingId),
    onNext: () => setSelectedIndex((i) => Math.min(i + 1, list.length - 1)),
    onPrev: () => setSelectedIndex((i) => Math.max(i - 1, 0)),
    onApprove: () => {
      const item = list[selectedIndex];
      if (item) approveM.mutate(item.id);
    },
    onHold: () => {
      const item = list[selectedIndex];
      if (item) holdM.mutate(item.id);
    },
    onSkip: () => {
      const item = list[selectedIndex];
      if (item) skipM.mutate(item.id);
    },
  });

  const isLoading = needsReviewQ.isLoading || awaitingRefQ.isLoading || approvedQ.isLoading;
  const isError = needsReviewQ.isError || awaitingRefQ.isError || approvedQ.isError;
  const totalItems = needsReviewTotal + approvedTotal;

  async function handleBulkApprove() {
    const ids = needsReview.filter((i) => i.status === "needs_review").map((i) => i.id);
    setBulkConfirmOpen(false);
    const results = await Promise.allSettled(ids.map((id) => approveM.mutateAsync(id)));
    const failures = results.filter((r) => r.status === "rejected").length;
    if (failures > 0) {
      toast.show(`Approved ${ids.length - failures} of ${ids.length}; ${failures} failed`, "error");
    } else {
      toast.show(`Approved ${ids.length} item(s)`, "success");
    }
  }

  async function handleStartGeneration() {
    if (!shopId) return;
    try {
      const job = await createJobM.mutateAsync("generate");
      setStoredJobId(shopId, job.id);
      navigate(`/shops/${shopId}/generate?job=${job.id}`);
    } catch {
      toast.show("Could not start generation", "error");
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner size={24} />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-6">
        <EmptyState
          title="Could not load items"
          description="Something went wrong reaching the server."
          action={
            <Button
              size="sm"
              onClick={() => {
                void needsReviewQ.refetch();
                void awaitingRefQ.refetch();
                void approvedQ.refetch();
              }}
            >
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  if (totalItems === 0) {
    return (
      <div className="p-6">
        <EmptyState
          title="No items to review yet"
          description="Extract and classify a menu first."
          action={
            <Link to={`/shops/${shopId}/setup`}>
              <Button size="sm">Go to setup</Button>
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
      <ReviewHeader
        shopName={shopQ.data?.name ?? "Review"}
        needsReviewTotal={needsReviewTotal}
        starting={createJobM.isPending}
        onStart={handleStartGeneration}
      />

      <ReviewTabs
        tab={tab}
        onChange={setTab}
        needsReviewTotal={needsReviewTotal}
        approvedTotal={approvedTotal}
        showBulkApprove={tab === "needs_review" && needsReview.some((i) => i.status === "needs_review")}
        onBulkApprove={() => setBulkConfirmOpen(true)}
      />

      {list.length === 0 ? (
        <EmptyState
          title={tab === "needs_review" ? "Nothing left to review" : "No approved items yet"}
        />
      ) : (
        <div className="flex flex-col gap-3">
          {list.map((item, idx) => (
            <ReviewCard
              key={item.id}
              item={item}
              selected={idx === selectedIndex}
              onSelect={() => setSelectedIndex(idx)}
              onApprove={() => approveM.mutate(item.id)}
              onSkip={() => skipM.mutate(item.id)}
              onSaveConcept={async (text) => {
                setEditingId(item.id);
                try {
                  await updateM.mutateAsync({ id: item.id, payload: { concept_text: text } });
                } finally {
                  setEditingId(null);
                }
              }}
              onUploadReference={async (file) => {
                await uploadRefM.mutateAsync({ id: item.id, file });
                toast.show("Reference uploaded", "success");
              }}
              busy={approveM.isPending || holdM.isPending || skipM.isPending}
            />
          ))}
        </div>
      )}

      <BulkApproveModal
        open={bulkConfirmOpen}
        onClose={() => setBulkConfirmOpen(false)}
        onConfirm={handleBulkApprove}
      />
    </div>
  );
}
