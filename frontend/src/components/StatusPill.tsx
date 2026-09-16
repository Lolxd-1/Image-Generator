/// components/StatusPill.tsx — colored status indicator for ItemStatus/JobStatus.
import { Badge } from "./Badge";
import type { BadgeTone } from "./Badge";
import type { ItemStatus, JobStatus } from "../api/types";

type Status = ItemStatus | JobStatus;

const TONE_BY_STATUS: Record<Status, BadgeTone> = {
  // ItemStatus
  new: "neutral",
  needs_review: "warn",
  awaiting_ref: "warn",
  approved: "accent",
  queued: "accent",
  generating: "accent",
  generated: "ok",
  hosted: "ok",
  failed: "danger",
  skipped: "neutral",
  // JobStatus (pending/running/failed overlap with above where identical)
  pending: "neutral",
  running: "accent",
  paused: "warn",
  done: "ok",
  cancelled: "neutral",
};

const LABEL_BY_STATUS: Record<Status, string> = {
  new: "New",
  needs_review: "Needs review",
  awaiting_ref: "Awaiting reference",
  approved: "Approved",
  queued: "Queued",
  generating: "Generating",
  generated: "Generated",
  hosted: "Hosted",
  failed: "Failed",
  skipped: "Skipped",
  pending: "Pending",
  running: "Running",
  paused: "Paused",
  done: "Done",
  cancelled: "Cancelled",
};

export interface StatusPillProps {
  status: Status;
  className?: string;
}

export function StatusPill({ status, className }: StatusPillProps) {
  return (
    <Badge tone={TONE_BY_STATUS[status]} className={className}>
      {LABEL_BY_STATUS[status]}
    </Badge>
  );
}
