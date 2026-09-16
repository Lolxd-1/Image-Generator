/// screens/setup/ReferenceSection.tsx — the reference-image input (SPEC.md
/// §6 POST /api/shops/{id}/reference). Renders the returned StyleProfile as
/// read-only chips so the admin can catch a misread reference before it
/// poisons every generated dish photo.
import { useState } from "react";
import { ApiError } from "../../api/client";
import { useUploadReference } from "../../api/hooks";
import type { StyleProfile } from "../../api/types";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card, CardHeader, CardTitle } from "../../components/Card";
import { DropZone } from "../../components/DropZone";
import { ImageTile } from "../../components/ImageTile";
import { Spinner } from "../../components/Spinner";

const CHIP_FIELDS: Array<{ key: "camera_angle" | "lighting" | "surface" | "background" | "mood"; label: string }> = [
  { key: "camera_angle", label: "Camera angle" },
  { key: "lighting", label: "Lighting" },
  { key: "surface", label: "Surface" },
  { key: "background", label: "Background" },
  { key: "mood", label: "Mood" },
];

export function ReferenceSection({
  shopId,
  referenceImageId,
  styleProfile,
}: {
  shopId: string;
  referenceImageId: string | null;
  styleProfile: StyleProfile | null;
}) {
  const [replacing, setReplacing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const uploadReference = useUploadReference(shopId);

  async function onFiles(files: File[]) {
    const file = files[0];
    if (!file) return;
    setError(null);
    try {
      await uploadReference.mutateAsync(file);
      setReplacing(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not read that image.");
    }
  }

  const hasReference = Boolean(referenceImageId);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Reference image</CardTitle>
      </CardHeader>
      <p className="mb-3 text-xs text-base-400">
        One photo that sets the visual style every generated dish photo will
        follow — camera angle, lighting, surface, mood.
      </p>

      {hasReference && !replacing && (
        <div className="flex flex-wrap items-start gap-4">
          <ImageTile imageId={referenceImageId} size="lg" label="Reference" />
          <div className="min-w-[200px] flex-1">
            {styleProfile ? (
              <div className="flex flex-col gap-2">
                <p className="text-xs font-medium text-base-300">Detected style</p>
                <div className="flex flex-wrap gap-1.5">
                  {CHIP_FIELDS.map(({ key, label }) => (
                    <Badge key={key} tone="accent">
                      {label}: {styleProfile[key]}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-xs text-base-400">Style not detected yet.</p>
            )}
            <Button className="mt-3" size="sm" variant="secondary" onClick={() => setReplacing(true)}>
              Replace reference
            </Button>
          </div>
        </div>
      )}

      {(!hasReference || replacing) && (
        <div className="flex flex-col gap-2">
          {uploadReference.isPending ? (
            <div className="flex items-center justify-center gap-2 py-6">
              <Spinner size={18} />
              <span className="text-xs text-base-400">Reading style from image…</span>
            </div>
          ) : (
            <DropZone
              onFiles={onFiles}
              multiple={false}
              accept="image/*"
              label="Drop a reference photo, or click to browse"
              hint="One image. JPG or PNG."
            />
          )}
          {error && <p className="text-xs text-danger-400">{error}</p>}
          {replacing && (
            <Button
              size="sm"
              variant="ghost"
              className="self-start"
              onClick={() => setReplacing(false)}
            >
              Cancel
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
