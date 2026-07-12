import { useState } from "react";
import { useSession } from "../session/useSession";
import { EditModal, type EditField } from "./EditModal";
import { ReasonModal } from "./ReasonModal";
import type {
  ItemType,
  RelationshipProposalInput,
  ReviewDecision,
} from "../types/viewModels";

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
  sourceItem,
  onCleared,
}: {
  itemType: ItemType;
  itemKey: string;
  confidence?: number | null;
  editFields?: EditField[];
  editTitle?: string;
  sourceItem?: RelationshipProposalInput;
  onCleared?: () => void;
}) {
  const { decide, decisionFor, isCommitted, clearDecision, busy } = useSession();
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const decision = decisionFor(itemType, itemKey);
  const committed = isCommitted(itemType, itemKey);
  const locked = busy || committed;
  // A decision can be cleared only while it is still uncommitted.
  const canClear = decision !== "pending" && !committed;

  const approve = () =>
    decide({
      itemType, itemKey, action: "approve", sourceItem,
      confidence: confidence ?? null,
    });

  const submitReject = (reason: string) => {
    setRejecting(false);
    decide({ itemType, itemKey, action: "reject", sourceItem, reason });
  };

  const submitEdit = (changes: Record<string, string>, reason: string) => {
    setEditing(false);
    decide({
      itemType, itemKey, action: "edit", payload: changes, sourceItem, reason,
      confidence: confidence ?? null,
    });
  };

  const clear = async () => {
    if (await clearDecision(itemType, itemKey)) onCleared?.();
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
      <button className="btn btn--reject" disabled={locked} onClick={() => setRejecting(true)}>Reject</button>
      {canClear && (
        <button
          className="btn btn--clear"
          disabled={busy}
          title="Revert this decision to pending"
          onClick={() => void clear()}
        >
          Clear
        </button>
      )}

      {editing && editFields && (
        <EditModal
          title={editTitle ?? `Edit ${itemKey}`}
          fields={editFields}
          onSubmit={submitEdit}
          onClose={() => setEditing(false)}
        />
      )}

      {rejecting && (
        <ReasonModal
          title={`Reject ${itemKey}`}
          prompt="Rejecting routes this item to the correction log. Give a reason."
          confirmLabel="Reject"
          onSubmit={submitReject}
          onClose={() => setRejecting(false)}
        />
      )}
    </div>
  );
}
