/// components/Input.tsx — labeled text input with inline error state.
import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";
import { cn } from "../lib/cn";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, id, className, ...rest }, ref) => {
    const inputId = id ?? rest.name;
    return (
      <label className="flex flex-col gap-1.5" htmlFor={inputId}>
        {label && (
          <span className="text-xs font-medium text-base-300">{label}</span>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            "h-9 rounded-md border bg-base-900 px-3 text-sm text-base-100 placeholder:text-base-400",
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
Input.displayName = "Input";
