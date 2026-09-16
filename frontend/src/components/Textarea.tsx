/// components/Textarea.tsx — labeled multi-line text input.
import { forwardRef } from "react";
import type { TextareaHTMLAttributes } from "react";
import { cn } from "../lib/cn";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, error, hint, id, className, rows = 4, ...rest }, ref) => {
    const inputId = id ?? rest.name;
    return (
      <label className="flex flex-col gap-1.5" htmlFor={inputId}>
        {label && (
          <span className="text-xs font-medium text-base-300">{label}</span>
        )}
        <textarea
          ref={ref}
          id={inputId}
          rows={rows}
          className={cn(
            "resize-y rounded-md border bg-base-900 px-3 py-2 text-sm text-base-100 placeholder:text-base-400",
            "border-base-600 transition-colors",
            "focus:border-accent-500",
            error && "border-danger-500",
            className,
          )}
          {...rest}
        />
        {error ? (
          <span className="text-xs text-danger-400">{error}</span>
        ) : hint ? (
          <span className="text-xs text-base-400">{hint}</span>
        ) : null}
      </label>
    );
  },
);
Textarea.displayName = "Textarea";
