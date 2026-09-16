/// screens/catalog/ExportPanel.tsx — validate then export to the SmartBiz
/// .xlsx (SPEC.md §6/§9). Export stays disabled until validation is clean.
//
// The export Job (POST /shops/{id}/jobs/export) and the resulting Export
// row are different entities with different ids — the workbook lives at
// GET /api/exports/{export_id}, not the job id. useShopExports() is the
// source of truth for that id; the newest record is the one this run just
// produced (export jobs run to completion inside the POST per SPEC.md §6).
import { useState } from "react";
import { useCreateJob, useExportValidate, useShopExports, exportFileUrl, shopImagesZipUrl } from "../../api/hooks";
import type { Item, RowError } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardHeader, CardTitle } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { useToast } from "../../components/Toast";

export interface ExportPanelProps {
  shopId: string | undefined;
  items: Item[];
  onJumpToItem: (itemId: string) => void;
}

export function ExportPanel({ shopId, items, onJumpToItem }: ExportPanelProps) {
  const validateQ = useExportValidate(shopId);
  const exportsQ = useShopExports(shopId);
  const createExportM = useCreateJob(shopId ?? "");
  const toast = useToast();
  const [exported, setExported] = useState(false);

  const errors: RowError[] = validateQ.data ?? [];
  const clean = validateQ.isSuccess && errors.length === 0;
  const latestExport = exportsQ.data?.[0] ?? null;

  function itemLabel(itemId: string): string {
    return items.find((i) => i.id === itemId)?.name ?? itemId;
  }

  async function handleExport() {
    try {
      await createExportM.mutateAsync("export");
      await exportsQ.refetch();
      setExported(true);
      toast.show("Export generated", "success");
    } catch {
      toast.show("Export failed", "error");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Export to SmartBiz</CardTitle>
        {shopId && (
          <a href={shopImagesZipUrl(shopId)} className="text-xs text-accent-400 underline">
            Download all images (.zip)
          </a>
        )}
      </CardHeader>

      <p className="mb-3 text-xs text-base-400">
        The exported file uploads to SmartBiz as-is, without manual correction. Fix every row
        error below before exporting.
      </p>

      {validateQ.isLoading && (
        <div className="flex justify-center py-3">
          <Spinner size={18} />
        </div>
      )}

      {validateQ.isError && (
        <div className="flex items-center justify-between text-xs text-danger-400">
          <span>Could not run validation.</span>
          <Button size="sm" variant="ghost" onClick={() => void validateQ.refetch()}>
            Retry
          </Button>
        </div>
      )}

      {validateQ.isSuccess && errors.length > 0 && (
        <ul className="mb-3 flex max-h-48 flex-col gap-1 overflow-y-auto">
          {errors.map((e, idx) => (
            <li key={`${e.item_id}-${e.field}-${idx}`}>
              <button
                onClick={() => onJumpToItem(e.item_id)}
                className="w-full rounded-sm border border-danger-600/30 bg-danger-600/5 px-2 py-1 text-left text-xs text-danger-400 hover:bg-danger-600/10"
              >
                Row {e.row} · {e.field}: {e.message} ({itemLabel(e.item_id)})
              </button>
            </li>
          ))}
        </ul>
      )}

      {validateQ.isSuccess && errors.length === 0 && (
        <p className="mb-3 text-xs text-ok-400">All rows valid — ready to export.</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={handleExport} disabled={!clean || createExportM.isPending} loading={createExportM.isPending}>
          Export .xlsx
        </Button>
        {exported && latestExport && (
          <a href={exportFileUrl(latestExport.id)} className="text-xs text-accent-400 underline">
            Download {latestExport.filename} ({latestExport.row_count} rows)
          </a>
        )}
      </div>

      {exported && latestExport && latestExport.included_without_image > 0 && (
        <p className="mt-2 text-xs text-warn-400">
          {latestExport.included_without_image} row(s) included without an image.
        </p>
      )}
    </Card>
  );
}
