import { useMemo } from "react";
import { useData } from "../session/useData";
import { byAttentionThenConfidence } from "../lib/review";
import { ORIENTATIONS } from "../lib/vocab";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { ReviewActions } from "../components/ReviewActions";

/**
 * Zone orientation is intentionally empty for W0-W6: no accepted zone dataset
 * was delivered, so this view must not imply hidden placeholder review work.
 */
export function ZonesView() {
  const { zones, loading, error } = useData();

  const rows = useMemo(() => [...zones].sort(byAttentionThenConfidence), [zones]);

  if (loading) return <p className="muted">Loading zones...</p>;
  if (error) return <p className="error">{error}</p>;

  return (
    <div className="view">
      <header className="view__head">
        <h2>Zone orientation</h2>
        <p className="muted">
          {rows.length} zones - Floor 02 - no accepted W0-W6 zone dataset
        </p>
      </header>

      <div className="note note--info">
        Zone orientation was not delivered as an accepted W0-W6 dataset. This tab
        stays empty until real zone records are supplied and reviewed.
      </div>

      {rows.length === 0 ? (
        <p className="muted">No zone records are available for review.</p>
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
                <td><ConfidenceBadge confidence={z.confidence} flagged={z.reviewRequired} /></td>
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
