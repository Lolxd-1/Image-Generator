/// components/ConfidenceBar.tsx — 0-100 confidence meter. Classification's
/// CONFIDENCE_AUTO_APPROVE threshold (SPEC.md §5) is 90; colour reflects it.
import { cn } from "../lib/cn";

export interface ConfidenceBarProps {
  value: number | null;
  className?: string;
}

const AUTO_APPROVE_THRESHOLD = 90;

function toneFor(value: number): string {
  if (value >= AUTO_APPROVE_THRESHOLD) return "bg-ok-500";
  if (value >= 60) return "bg-warn-500";
  return "bg-danger-500";
}

export function ConfidenceBar({ value, className }: ConfidenceBarProps) {
  if (value === null) {
    return <span className="text-xs text-base-400">—</span>;
  }
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-base-700">
        <div
          className={cn("h-full rounded-full", toneFor(pct))}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-8 text-right text-xs tabular-nums text-base-300">
        {pct}
      </span>
    </div>
  );
}
