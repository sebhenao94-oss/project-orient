import { useMemo } from "react";
import { useData } from "../session/DataContext";
import { byConfidenceAsc } from "../lib/review";
import { ORIENTATIONS } from "../lib/vocab";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { ReviewActions } from "../components/ReviewActions";

/**
 * Zone orientation — confirm or correct each zone's orientation label.
 * Real zone data is produced in W7; the mock data here is illustrative so the
 * view and its review flow are ready when that data lands.
 */
export function ZonesView() {
  const { zones, loading, error } = useData();

  const rows = useMemo(() => [...zones].sort(byConfidenceAsc), [zones]);

  if (loading) return <p className="muted">Loading zones…</p>;
  if (error) return <p className="error">{error}</p>;

  return (
    <div className="view">
      <header className="view__head">
        <h2>Zone orientation</h2>
        <p className="muted">
          {rows.length} zones · Floor 02 · confirm or correct each orientation label
        </p>
      </header>

      <div className="note note--info">
        Orientation extraction is a W7 deliverable — these rows are placeholder data
        so the confirm/correct flow is ready to wire to real zones.
      </div>

      {rows.length === 0 ? (
        <p className="muted">No zones yet.</p>
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th>Confidence</th>
              <th>Zone</th>
              <th>Floor</th>
              <th>Orientation</th>
              <th className="grid__actions">Decision</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((z) => (
              <tr key={z.key} className={z.reviewRequired ? "row--flagged" : undefined}>
                <td><ConfidenceBadge confidence={z.confidence} /></td>
                <td className="mono">{z.key}</td>
                <td>{z.floor}</td>
                <td>
                  {z.orientation ? (
                    <span className="tag">{z.orientation}</span>
                  ) : (
                    <span className="muted">unclassified</span>
                  )}
                </td>
                <td className="grid__actions">
                  <ReviewActions
                    itemType="zone"
                    itemKey={z.key}
                    confidence={z.confidence}
                    editTitle={`Correct ${z.key} orientation`}
                    editFields={[
                      { key: "orientation", label: "Orientation", value: z.orientation ?? "unclassified", type: "select", options: ORIENTATIONS },
                      { key: "floor", label: "Floor", value: z.floor },
                    ]}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
