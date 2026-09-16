/// screens/review/ReviewHeader.tsx — title, keyboard-shortcut legend, and
/// the primary "Start generation" action (disabled with a reason while
/// anything still needs review, per SPEC.md §9).
import { Button } from "../../components/Button";

export interface ReviewHeaderProps {
  shopName: string;
  needsReviewTotal: number;
  starting: boolean;
  onStart: () => void;
}

export function ReviewHeader({ shopName, needsReviewTotal, starting, onStart }: ReviewHeaderProps) {
  return (
    <header className="flex items-center justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold text-base-100">{shopName}</h1>
        <p className="text-xs text-base-400">
          Shortcuts: <kbd className="rounded bg-base-800 px-1">j</kbd>/
          <kbd className="rounded bg-base-800 px-1">k</kbd> move ·{" "}
          <kbd className="rounded bg-base-800 px-1">a</kbd> approve ·{" "}
          <kbd className="rounded bg-base-800 px-1">h</kbd> hold ·{" "}
          <kbd className="rounded bg-base-800 px-1">s</kbd> skip
        </p>
      </div>
      <div className="flex flex-col items-end gap-1">
        <Button onClick={onStart} disabled={needsReviewTotal > 0 || starting} loading={starting}>
          Start generation
        </Button>
        {needsReviewTotal > 0 && (
          <span className="text-xs text-warn-400">{needsReviewTotal} item(s) still need review</span>
        )}
      </div>
    </header>
  );
}
