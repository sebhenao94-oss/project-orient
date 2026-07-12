import { useMemo } from "react";
import { useData } from "../session/useData";
import { byAttentionThenConfidence } from "../lib/review";
import { EQUIPMENT_TYPES } from "../lib/vocab";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { ReviewActions } from "../components/ReviewActions";

/** Equipment list — approve / edit / reject, confidence-ascending by default. */
export function EquipmentView() {
  const { equipment, loading, error } = useData();

  const rows = useMemo(() => [...equipment].sort(byAttentionThenConfidence), [equipment]);

  if (loading) return <p className="muted">Loading equipment…</p>;
  if (error) return <p className="error">{error}</p>;
  if (rows.length === 0) return <p className="muted">No equipment to review.</p>;

  return (
    <div className="view">
      <header className="view__head">
        <h2>Equipment</h2>
        <p className="muted">
          {rows.length} items · Floor 02 · flagged &amp; low-confidence first
        </p>
      </header>

      <table className="grid">
        <thead>
          <tr>
            <th>Confidence</th>
            <th>Name</th>
            <th>Type</th>
            <th>Status</th>
            <th>Evidence</th>
            <th>Review note</th>
            <th className="grid__actions">Decision</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.key} className={e.reviewRequired ? "row--flagged" : undefined}>
              <td><ConfidenceBadge confidence={e.confidence} flagged={e.reviewRequired} /></td>
              <td className="mono">{e.name}</td>
              <td>{e.equipmentType}</td>
              <td>
                <span className="tag">{e.status}</span>
                <span className="tag tag--muted">{e.discrepancyCategory}</span>
              </td>
              <td className="evidence">
                <span className={e.inTopics ? "ev ev--on" : "ev ev--off"}>topics</span>
                <span className={e.inDrawings ? "ev ev--on" : "ev ev--off"}>drawings</span>
              </td>
              <td className="muted small">{e.reviewReason ?? "—"}</td>
              <td className="grid__actions">
                {e.status === "floor_ambiguous" ? (
                  <span className="muted small">Resolved as out-of-scope floor evidence</span>
                ) : (
                  <ReviewActions
                    itemType="equipment"
                    itemKey={e.key}
                    confidence={e.confidence}
                    editTitle={`Edit ${e.name}`}
                    editFields={[
                      { key: "canonical_name", label: "Canonical name", value: e.name },
                      { key: "equipment_type", label: "Type", value: e.equipmentType, type: "select", options: EQUIPMENT_TYPES },
                      { key: "floor", label: "Floor", value: e.floor },
                    ]}
                  />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
