/// screens/generate/GenerateTile.tsx — one dish's tile in the live
/// generation grid. `item_failed` (SPEC.md §6) means this ONE dish gave up
/// while the run keeps going — the tile must read as "this dish needs a
/// retry", never as "the whole run died".
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { ImageTile } from "../../components/ImageTile";
import { Spinner } from "../../components/Spinner";
import { cn } from "../../lib/cn";
import type { Item } from "../../api/types";

export type TilePhase = "pending" | "generating" | "done" | "failed";

export function phaseFor(status: Item["status"]): TilePhase {
  switch (status) {
    case "queued":
      return "pending";
    case "generating":
      return "generating";
    case "generated":
    case "hosted":
      return "done";
    case "failed":
      return "failed";
    default:
      return "pending";
  }
}

export interface GenerateTileProps {
  item: Item;
  onRetry: () => void;
  retrying?: boolean;
}

export function GenerateTile({ item, onRetry, retrying }: GenerateTileProps) {
  const phase = phaseFor(item.status);
  return (
    <div
      id={`generate-item-${item.id}`}
      className={cn(
        "flex flex-col gap-2 rounded-lg border p-2 transition-colors",
        phase === "failed" ? "border-danger-600/50 bg-danger-600/5" : "border-base-700 bg-base-900",
      )}
    >
      <div className="relative mx-auto">
        <ImageTile imageId={item.image_id} label={item.name} size="md" />
        {phase === "generating" && (
          <div className="absolute inset-0 flex items-center justify-center rounded-md bg-base-950/60">
            <Spinner size={20} />
          </div>
        )}
      </div>
      <div className="flex items-center justify-between gap-1">
        <span className="truncate text-xs text-base-300">{item.name}</span>
        <PhaseBadge phase={phase} />
      </div>
      {phase === "failed" && (
        <div className="flex flex-col gap-1">
          {item.last_error && (
            <p className="truncate text-[11px] text-danger-400" title={item.last_error}>
              {item.last_error}
            </p>
          )}
          <Button size="sm" variant="secondary" onClick={onRetry} loading={retrying}>
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}

function PhaseBadge({ phase }: { phase: TilePhase }) {
  switch (phase) {
    case "pending":
      return <Badge tone="neutral">Pending</Badge>;
    case "generating":
      return <Badge tone="accent">Generating</Badge>;
    case "done":
      return <Badge tone="ok">Done</Badge>;
    case "failed":
      return <Badge tone="danger">Failed</Badge>;
  }
}
