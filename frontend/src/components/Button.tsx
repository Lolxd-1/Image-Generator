/// components/Button.tsx — the one clickable-action primitive for the app.
import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../lib/cn";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-accent-600 text-white hover:bg-accent-500 disabled:bg-base-700",
  secondary:
    "bg-base-800 text-base-100 border border-base-600 hover:bg-base-700",
  danger: "bg-danger-600 text-white hover:bg-danger-500 disabled:bg-base-700",
  ghost: "bg-transparent text-base-200 hover:bg-base-800",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-xs gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { variant = "primary", size = "md", loading, disabled, className, children, ...rest },
    ref,
  ) => {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          "inline-flex items-center justify-center rounded-md font-medium transition-colors",
          "disabled:cursor-not-allowed disabled:opacity-60",
          VARIANT[variant],
          SIZE[size],
          className,
        )}
        {...rest}
      >
        {loading && <Spinner size={size === "sm" ? 12 : 14} />}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
