/// screens/Setup.tsx — Setup screen shell: the 4 required inputs (SPEC.md
/// §2 Shop model + §6 shop routes) before extraction can run — menu photos,
/// reference image, the 7 context metrics, and the shop's ImgBB key.
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useCreateJob, useShop } from "../api/hooks";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { Spinner } from "../components/Spinner";
import { useToast } from "../components/Toast";
import { ContextForm } from "./setup/ContextForm";
import { ImgbbKeySection } from "./setup/ImgbbKeySection";
import { MenuPhotosSection } from "./setup/MenuPhotosSection";
import type { MenuPhotoRow } from "./setup/MenuPhotosSection";
import { ReferenceSection } from "./setup/ReferenceSection";

export default function Setup() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const { data: shop, isLoading, isError, error } = useShop(id);
  const [menuRows, setMenuRows] = useState<MenuPhotoRow[]>([]);
  const createJob = useCreateJob(id ?? "");

  if (!id) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-8">
        <EmptyState title="No shop selected" description="Go back to Shops and pick one." />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner size={24} />
      </div>
    );
  }

  if (isError || !shop) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-8">
        <EmptyState
          title="Could not load this shop"
          description={error instanceof ApiError ? error.message : "Please refresh and try again."}
        />
      </div>
    );
  }

  const missing: string[] = [];
  if (menuRows.length === 0) missing.push("at least one menu photo");
  if (!shop.reference_image_id) missing.push("a reference image");
  const canExtract = missing.length === 0;

  async function onStartExtraction() {
    try {
      await createJob.mutateAsync("extract");
      navigate(`/shops/${id}/review`);
    } catch (err) {
      toast.show(err instanceof ApiError ? err.message : "Could not start extraction.", "error");
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-base-100">{shop.name}</h1>
        <p className="text-xs text-base-400">Set up the shop before extracting its menu.</p>
      </div>

      <div className="flex flex-col gap-5">
        <MenuPhotosSection shopId={id} rows={menuRows} onRowsChange={setMenuRows} />
        <ReferenceSection
          shopId={id}
          referenceImageId={shop.reference_image_id}
          styleProfile={shop.style_profile}
        />
        <ContextForm shop={shop} />
        <ImgbbKeySection shopId={id} hasKey={shop.has_imgbb_key} />
      </div>

      <div className="sticky bottom-0 mt-6 flex items-center justify-between gap-3 border-t border-base-700 bg-base-950/95 py-4 backdrop-blur-sm">
        <p className="text-xs text-base-400">
          {canExtract ? "Ready to extract the menu." : `Still need: ${missing.join(", ")}.`}
        </p>
        <Button onClick={onStartExtraction} disabled={!canExtract} loading={createJob.isPending}>
          Start extraction
        </Button>
      </div>
    </div>
  );
}
