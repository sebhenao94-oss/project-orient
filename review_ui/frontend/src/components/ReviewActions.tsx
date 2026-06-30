import { useState } from "react";
import { useSession } from "../session/SessionContext";
import { EditModal, type EditField } from "./EditModal";
import type { ItemType, ReviewDecision } from "../types/viewModels";

const LABEL: Record<ReviewDecision, string> = {
  pending: "Pending",
  approved: "Approved",
  edited: "Edited",
  rejected: "Rejected",
};

/**
 * Approve / Edit / Reject for a single item. Edit opens the structured EditModal
 * (any attribute, typed, with a reason). Once an item is committed it locks.
 */
export function ReviewActions({
  itemType,
  itemKey,
  confidence,
  editFields,
  editTitle,
}: {
  itemType: ItemType;
  itemKey: string;
  confidence?: number | null;
  editFields?: EditField[];
  editTitle?: string;
}) {
  const { decide, decisionFor, isCommitted, busy } = useSession();
  const [editing, setEditing] = useState(false);
  const decision = decisionFor(itemType, itemKey);
  const committed = isCommitted(itemType, itemKey);
  const locked = busy || committed;

  const approve = () =>
    decide({ itemType, itemKey, action: "approve", confidence: confidence ?? null });

  const reject = () => {
    const reason = window.prompt("Reason for rejection");
    if (!reason || !reason.trim()) return;
    decide({ itemType, itemKey, action: "reject", reason });
  };

  const submitEdit = (changes: Record<string, string>, reason: string) => {
    setEditing(false);
    decide({ itemType, itemKey, action: "edit", payload: changes, reason, confidence: confidence ?? null });
  };

  return (
    <div className="actions">
      <span className={`decision decision--${decision}`}>
        {LABEL[decision]}
        {committed && <span className="lock" title="committed to DB"> 🔒</span>}
      </span>
      <button className="btn btn--approve" disabled={locked} onClick={approve}>Approve</button>
      <button
        className="btn btn--edit"
        disabled={locked || !editFields?.length}
        onClick={() => setEditing(true)}
      >
        Edit
      </button>
      <button className="btn btn--reject" disabled={locked} onClick={reject}>Reject</button>

      {editing && editFields && (
        <EditModal
          title={editTitle ?? `Edit ${itemKey}`}
          fields={editFields}
          onSubmit={submitEdit}
          onClose={() => setEditing(false)}
        />
      )}
    </div>
  );
}
