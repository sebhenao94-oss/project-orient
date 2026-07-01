import { useState } from "react";

/**
 * Reason-only modal — used by Reject (and any action that needs a justification
 * but no field edits). Mirrors the EditModal styling so the two flows feel the
 * same. The reason is what the brief routes to correction_log.
 */
export function ReasonModal({
  title,
  prompt,
  confirmLabel = "Confirm",
  onSubmit,
  onClose,
}: {
  title: string;
  prompt: string;
  confirmLabel?: string;
  onSubmit: (reason: string) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const canSubmit = reason.trim().length > 0;

  return (
    <div className="modal__overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal__title">{title}</h3>
        <p className="muted small">{prompt}</p>
        <label className="field">
          <span className="field__label">Reason (required)</span>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} autoFocus />
        </label>
        <div className="modal__actions">
          <span className="modal__spacer" />
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn--reject" disabled={!canSubmit} onClick={() => onSubmit(reason.trim())}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
