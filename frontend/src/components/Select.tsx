/// components/Select.tsx — labeled native select (kept native for a11y + keyboard use).
import { forwardRef } from "react";
import type { SelectHTMLAttributes } from "react";
import { cn } from "../lib/cn";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  options: SelectOption[];
  placeholder?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, options, placeholder, id, className, ...rest }, ref) => {
    const inputId = id ?? rest.name;
    return (
      <label className="flex flex-col gap-1.5" htmlFor={inputId}>
        {label && (
          <span className="text-xs font-medium text-base-300">{label}</span>
        )}
        <select
          ref={ref}
          id={inputId}
          className={cn(
            "h-9 rounded-md border bg-base-900 px-2.5 text-sm text-base-100",
            "border-base-600 transition-colors",
            "focus:border-accent-500",
            error && "border-danger-500",
            className,
          )}
          {...rest}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {error && <span className="text-xs text-danger-400">{error}</span>}
      </label>
    );
  },
);
Select.displayName = "Select";
