/// screens/review/BulkApproveModal.tsx — confirmation for the destructive-ish
/// "approve all remaining" bulk action (SPEC.md §7: destructive actions confirm).
import { Button } from "../../components/Button";
import { Modal } from "../../components/Modal";

export interface BulkApproveModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function BulkApproveModal({ open, onClose, onConfirm }: BulkApproveModalProps) {
  return (
    <Modal open={open} onClose={onClose} title="Approve all remaining?">
      <p className="mb-4 text-sm text-base-300">
        This approves every item currently in "Needs review" that doesn't need a manual
        reference photo. This cannot be undone from here.
      </p>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={onConfirm}>Approve all</Button>
      </div>
    </Modal>
  );
}
