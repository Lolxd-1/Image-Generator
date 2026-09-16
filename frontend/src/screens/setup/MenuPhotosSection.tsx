/// screens/setup/MenuPhotosSection.tsx — multi-file menu photo input
/// (SPEC.md §6 POST /api/shops/{id}/menus, DELETE .../menus/{mid}).
//
// Photos already attached to the shop are loaded from the server on mount, so
// a reload never hides them or invites a duplicate re-upload. Thumbnails come
// from the server for stored photos, and from a local object URL for a file
// uploaded in this session (which avoids a round-trip for a preview we already
// have the bytes for).
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { menuFileUrl, useDeleteMenu, useShopMenus, useUploadMenus } from "../../api/hooks";
import type { MenuUpload } from "../../api/types";
import { Card, CardHeader, CardTitle } from "../../components/Card";
import { DropZone } from "../../components/DropZone";
import { Spinner } from "../../components/Spinner";

export interface MenuPhotoRow {
  upload: MenuUpload;
  previewUrl: string | null;
}

export function MenuPhotosSection({
  shopId,
  rows,
  onRowsChange,
}: {
  shopId: string;
  rows: MenuPhotoRow[];
  onRowsChange: (rows: MenuPhotoRow[]) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [duplicateNotice, setDuplicateNotice] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const uploadMenus = useUploadMenus(shopId);
  const deleteMenu = useDeleteMenu(shopId);
  const urlsRef = useRef<string[]>([]);
  const existing = useShopMenus(shopId);

  // Seed from the server once, then let local state own the list so an
  // optimistic add/remove is not clobbered by a refetch mid-interaction.
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current || !existing.data) return;
    seededRef.current = true;
    if (existing.data.length === 0) return;
    onRowsChange(existing.data.map((upload) => ({ upload, previewUrl: null })));
  }, [existing.data, onRowsChange]);

  useEffect(
    () => () => {
      urlsRef.current.forEach((u) => URL.revokeObjectURL(u));
    },
    [],
  );

  async function onFiles(files: File[]) {
    setError(null);
    setDuplicateNotice(null);
    try {
      const uploaded = await uploadMenus.mutateAsync(files);
      const knownIds = new Set(rows.map((r) => r.upload.id));
      const next = [...rows];
      let dupCount = 0;
      uploaded.forEach((upload, i) => {
        if (knownIds.has(upload.id)) {
          dupCount += 1;
          return;
        }
        const file = files[i];
        const previewUrl = file ? URL.createObjectURL(file) : null;
        if (previewUrl) urlsRef.current.push(previewUrl);
        next.push({ upload, previewUrl });
      });
      onRowsChange(next);
      if (dupCount > 0) {
        setDuplicateNotice(
          `${dupCount} file${dupCount > 1 ? "s were" : " was"} already uploaded — skipped.`,
        );
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not upload those files.");
    }
  }

  async function onRemove(row: MenuPhotoRow) {
    if (!window.confirm(`Remove "${row.upload.filename}"?`)) return;
    setDeletingId(row.upload.id);
    try {
      await deleteMenu.mutateAsync(row.upload.id);
      if (row.previewUrl) URL.revokeObjectURL(row.previewUrl);
      onRowsChange(rows.filter((r) => r.upload.id !== row.upload.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove that file.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Menu photos</CardTitle>
      </CardHeader>
      <p className="mb-3 text-xs text-base-400">
        Photos of the physical menu. Upload the same file twice and it's
        recognised as a duplicate rather than added again.
      </p>

      <DropZone
        onFiles={onFiles}
        multiple
        accept="image/*"
        label="Drop menu photos here, or click to browse"
        disabled={uploadMenus.isPending}
      />
      {uploadMenus.isPending && (
        <div className="mt-2 flex items-center gap-2 text-xs text-base-400">
          <Spinner size={14} /> Uploading…
        </div>
      )}
      {duplicateNotice && <p className="mt-2 text-xs text-warn-400">{duplicateNotice}</p>}
      {error && <p className="mt-2 text-xs text-danger-400">{error}</p>}

      {rows.length === 0 && !uploadMenus.isPending && (
        <p className="mt-3 text-xs text-base-500">No menu photos uploaded yet.</p>
      )}

      {rows.length > 0 && (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {rows.map((row) => (
            <div
              key={row.upload.id}
              className="relative overflow-hidden rounded-md border border-base-700 bg-base-800"
            >
              {/* Local object URL for a file just uploaded, otherwise the
                  stored copy from the server. */}
              <img
                src={row.previewUrl ?? menuFileUrl(shopId, row.upload.id)}
                alt={row.upload.filename}
                loading="lazy"
                className="h-24 w-full object-cover"
              />
              <div className="flex items-center justify-between gap-1 px-1.5 py-1">
                <span className="truncate text-[10px] text-base-300">{row.upload.filename}</span>
                <button
                  type="button"
                  onClick={() => onRemove(row)}
                  disabled={deletingId === row.upload.id}
                  aria-label={`Remove ${row.upload.filename}`}
                  className="shrink-0 text-base-400 hover:text-danger-400"
                >
                  {deletingId === row.upload.id ? <Spinner size={10} /> : "×"}
                </button>
              </div>
              {row.upload.error && (
                <span className="absolute inset-x-0 top-0 truncate bg-danger-600/80 px-1 text-[9px] text-white">
                  {row.upload.error}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
