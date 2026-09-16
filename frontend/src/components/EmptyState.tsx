/// components/EmptyState.tsx — placeholder for empty lists/tables, with an
/// optional action (e.g. "Upload menu").
import type { ReactNode } from "react";
import { cn } from "../lib/cn";

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-base-700 px-6 py-12 text-center",
        className,
      )}
    >
      <p className="text-sm font-medium text-base-200">{title}</p>
      {description && (
        <p className="max-w-sm text-xs text-base-400">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
