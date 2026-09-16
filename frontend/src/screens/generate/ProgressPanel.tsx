/// screens/generate/ProgressPanel.tsx — overall progress bar, done/failed/
/// remaining counters, pause/resume, and the server-paced ETA readout.
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";

export interface ProgressPanelProps {
  done: number;
  failed: number;
  remaining: number;
  total: number;
  running: boolean;
  isComplete: boolean;
  /** The server's authoritative wait before the next step, in ms. */
  waitMs: number | null;
  etaSeconds: number | null;
  /** Dish the last step worked on. */
  lastItemName: string | null;
  onPause: () => void;
  onResume: () => void;
}

export function ProgressPanel({
  done,
  failed,
  remaining,
  total,
  running,
  isComplete,
  waitMs,
  etaSeconds,
  lastItemName,
  onPause,
  onResume,
}: ProgressPanelProps) {
  const pct = total > 0 ? Math.round(((done + failed) / total) * 100) : 0;
  return (
    <Card>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-base-100">
            {done + failed} / {total} processed
          </span>
          <Badge tone="ok">{done} done</Badge>
          <Badge tone="danger">{failed} failed</Badge>
          <Badge tone="neutral">{remaining} remaining</Badge>
        </div>
        {running ? (
          <Button size="sm" variant="secondary" onClick={onPause}>
            Pause
          </Button>
        ) : (
          <Button size="sm" onClick={onResume} disabled={isComplete}>
            {isComplete ? "Complete" : "Resume"}
          </Button>
        )}
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-base-800">
        <div className="h-full rounded-full bg-accent-600 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 flex gap-4 text-xs text-base-400">
        <span>
          Next step: {waitMs !== null ? `~${(waitMs / 1000).toFixed(1)}s` : "calculating..."}
        </span>
        <span>ETA: {etaSeconds !== null ? formatEta(etaSeconds) : "calculating..."}</span>
      </div>
      {running && lastItemName && (
        <p className="mt-2 text-xs text-base-400">Currently generating: {lastItemName}</p>
      )}
    </Card>
  );
}

function formatEta(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  if (m === 0) return `~${s}s`;
  return `~${m}m ${s}s`;
}
