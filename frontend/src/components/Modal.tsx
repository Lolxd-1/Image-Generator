/// components/Modal.tsx — centered dialog with backdrop, Escape-to-close,
/// used for confirmations, image previews, and small forms.
import { useEffect } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "../lib/cn";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  className?: string;
}

export function Modal({ open, onClose, title, children, className }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-base-950/70 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          "relative z-10 max-h-[85vh] w-full max-w-lg overflow-auto rounded-lg border border-base-700 bg-base-900 p-5 shadow-pop",
          className,
        )}
      >
        {title && (
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-base-100">{title}</h2>
            <button
              onClick={onClose}
              aria-label="Close"
              className="rounded-sm px-1.5 text-base-400 hover:bg-base-800 hover:text-base-100"
            >
              ×
            </button>
          </div>
        )}
        {children}
      </div>
    </div>,
    document.body,
  );
}
