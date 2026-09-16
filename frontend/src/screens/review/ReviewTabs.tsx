/// screens/review/ReviewTabs.tsx — the two review tabs plus bulk-approve
/// entry point (confirmation lives in BulkApproveModal).
import type { ReactNode } from "react";
import { Button } from "../../components/Button";

export type Tab = "needs_review" | "approved";

export interface ReviewTabsProps {
  tab: Tab;
  onChange: (tab: Tab) => void;
  needsReviewTotal: number;
  approvedTotal: number;
  showBulkApprove: boolean;
  onBulkApprove: () => void;
}

export function ReviewTabs({
  tab,
  onChange,
  needsReviewTotal,
  approvedTotal,
  showBulkApprove,
  onBulkApprove,
}: ReviewTabsProps) {
  return (
    <div className="flex items-center justify-between border-b border-base-700">
      <div className="flex gap-1">
        <TabButton active={tab === "needs_review"} onClick={() => onChange("needs_review")}>
          Needs review ({needsReviewTotal})
        </TabButton>
        <TabButton active={tab === "approved"} onClick={() => onChange("approved")}>
          Auto-approved ({approvedTotal})
        </TabButton>
      </div>
      {showBulkApprove && (
        <Button size="sm" variant="ghost" onClick={onBulkApprove}>
          Approve all remaining
        </Button>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        active
          ? "border-b-2 border-accent-500 px-3 py-2 text-sm font-medium text-base-100"
          : "border-b-2 border-transparent px-3 py-2 text-sm text-base-400 hover:text-base-200"
      }
    >
      {children}
    </button>
  );
}
