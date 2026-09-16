/// screens/generate/LogDrawer.tsx — collapsible live job-event log, fed by
/// useJobEvents (polled every 2s per SPEC.md §6).
import { Badge } from "../../components/Badge";
import { Spinner } from "../../components/Spinner";
import type { BadgeTone } from "../../components/Badge";
import type { JobEvent } from "../../api/types";

const LEVEL_TONE: Record<JobEvent["level"], BadgeTone> = {
  info: "neutral",
  warn: "warn",
  error: "danger",
};

export interface LogDrawerProps {
  open: boolean;
  onToggle: () => void;
  events: JobEvent[] | undefined;
  loading: boolean;
}

export function LogDrawer({ open, onToggle, events, loading }: LogDrawerProps) {
  const sorted = [...(events ?? [])].sort((a, b) => (a.ts < b.ts ? 1 : -1));
  return (
    <div className="rounded-lg border border-base-700 bg-base-900">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-base-300"
      >
        <span>Live log{sorted.length > 0 && ` (${sorted.length})`}</span>
        <span>{open ? "Hide -" : "Show +"}</span>
      </button>
      {open && (
        <div className="max-h-64 overflow-y-auto border-t border-base-700 px-3 py-2">
          {loading && sorted.length === 0 ? (
            <div className="flex justify-center py-4">
              <Spinner size={16} />
            </div>
          ) : sorted.length === 0 ? (
            <p className="py-3 text-center text-xs text-base-500">No events yet.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {sorted.map((ev) => (
                <li key={ev.id} className="flex items-start gap-2 text-xs">
                  <Badge tone={LEVEL_TONE[ev.level]} className="shrink-0">
                    {ev.level}
                  </Badge>
                  <span className="shrink-0 tabular-nums text-base-500">
                    {new Date(ev.ts).toLocaleTimeString()}
                  </span>
                  <span className="text-base-300">{ev.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
