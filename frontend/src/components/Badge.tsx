/// components/Badge.tsx — small tag/count chip.
import type { HTMLAttributes } from "react";
import { cn } from "../lib/cn";

export type BadgeTone = "neutral" | "accent" | "ok" | "warn" | "danger";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

const TONE: Record<BadgeTone, string> = {
  neutral: "bg-base-800 text-base-300 border-base-600",
  accent: "bg-accent-600/15 text-accent-400 border-accent-600/30",
  ok: "bg-ok-600/15 text-ok-400 border-ok-600/30",
  warn: "bg-warn-600/15 text-warn-400 border-warn-600/30",
  danger: "bg-danger-600/15 text-danger-400 border-danger-600/30",
};

export function Badge({ tone = "neutral", className, children, ...rest }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[11px] font-medium leading-none",
        TONE[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
