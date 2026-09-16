/// screens/review/useReviewShortcuts.ts — keyboard shortcuts for Review.tsx
/// per SPEC.md §7: a approve, h hold, s skip, j/k move selection. Disabled
/// while focus is inside an editable field (e.g. the concept-text editor) so
/// typing "a" or "s" there doesn't trigger an action.
import { useEffect } from "react";

export interface ReviewShortcutHandlers {
  onNext: () => void;
  onPrev: () => void;
  onApprove: () => void;
  onHold: () => void;
  onSkip: () => void;
  /** Shortcuts are ignored entirely while true (e.g. a concept edit is open). */
  suspended?: boolean;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable;
}

export function useReviewShortcuts({
  onNext,
  onPrev,
  onApprove,
  onHold,
  onSkip,
  suspended,
}: ReviewShortcutHandlers): void {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (suspended) return;
      if (isEditableTarget(e.target)) return;
      switch (e.key) {
        case "j":
          e.preventDefault();
          onNext();
          break;
        case "k":
          e.preventDefault();
          onPrev();
          break;
        case "a":
          e.preventDefault();
          onApprove();
          break;
        case "h":
          e.preventDefault();
          onHold();
          break;
        case "s":
          e.preventDefault();
          onSkip();
          break;
        default:
          break;
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onNext, onPrev, onApprove, onHold, onSkip, suspended]);
}
