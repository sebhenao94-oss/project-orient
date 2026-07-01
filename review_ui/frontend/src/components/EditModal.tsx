import { useState } from "react";

export interface EditField {
  key: string;
  label: string;
  value: string;
  type?: "text" | "select";
  options?: readonly string[];
}

/**
 * Structured "edit any attribute" editor. Pre-fills the item's current values,
 * lets the engineer change any field (dropdowns where the value is an enum), and
 * returns only the changed fields plus a reason. The changed-fields payload is
 * what the brief routes to correction_log and the few-shot pool — readable and
 * typed, not free text.
 */
export function EditModal({
  title,
  fields,
  onSubmit,
  onClose,
}: {
  title: string;
  fields: EditField[];
  onSubmit: (changes: Record<string, string>, reason: string) => void;
  onClose: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(fields.map((f) => [f.key, f.value])),
  );
  const [reason, setReason] = useState("");

  const changes: Record<string, string> = {};
  for (const f of fields) if (values[f.key] !== f.value) changes[f.key] = values[f.key];
  const changedCount = Object.keys(changes).length;
  const canSave = changedCount > 0 && reason.trim().length > 0;

  return (
    <div className="modal__overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal__title">{title}</h3>
        <p className="muted small">Change any attribute, then give a reason. Only changed fields are recorded.</p>

        <div className="modal__fields">
          {fields.map((f) => (
            <label key={f.key} className="field">
              <span className="field__label">{f.label}</span>
              {f.type === "select" ? (
                <select
                  value={values[f.key]}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                >
                  {!f.options?.includes(values[f.key]) && <option value={values[f.key]}>{values[f.key] || "—"}</option>}
                  {f.options?.map((o) => (
                    <option key={o} value={o}>{o}</option>
                  ))}
                </select>
              ) : (
                <input
                  value={values[f.key]}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                />
              )}
              {values[f.key] !== f.value && <span className="field__changed">was: {f.value || "—"}</span>}
            </label>
          ))}
        </div>

        <label className="field">
          <span className="field__label">Reason (required)</span>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
        </label>

        <div className="modal__actions">
          <span className="muted small">{changedCount} field(s) changed</span>
          <span className="modal__spacer" />
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn--commit" disabled={!canSave} onClick={() => onSubmit(changes, reason.trim())}>
            Save edit
          </button>
        </div>
      </div>
    </div>
  );
}
