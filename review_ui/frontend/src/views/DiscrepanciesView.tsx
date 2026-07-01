import { useMemo, useState } from "react";
import { useData } from "../session/DataContext";
import { ReviewActions } from "../components/ReviewActions";
import { DISCREPANCY_STATUSES, SEVERITIES } from "../lib/vocab";
import type { DiscrepancyVM, Severity } from "../types/viewModels";

type GroupBy = "severity_hint" | "floor" | "equipment_type";

const SEVERITY_ORDER: Record<Severity, number> = { high: 0, medium: 1, low: 2 };

function groupKey(d: DiscrepancyVM, by: GroupBy): string {
  if (by === "floor") return d.floor;
  if (by === "equipment_type") return d.equipmentType;
  return d.severity;
}

/** Human rollups like "Floor 2: 4 AHUs missing from drawings". */
function buildRollups(items: DiscrepancyVM[]): string[] {
  const counts = new Map<string, number>();
  for (const d of items) {
    if (d.status === "matched") continue;
    const label = `${d.floor.replace("Floor_0", "Floor ")}: ${d.equipmentType} ${d.status.replace(/_/g, " ")}`;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([label, n]) => `${n} × ${label}`);
}

/** Discrepancy report — W4 gap rows, grouped, with rollups and a review flow. */
export function DiscrepanciesView() {
  const { discrepancies, loading, error } = useData();
  const [by, setBy] = useState<GroupBy>("severity_hint");

  const rollups = useMemo(() => buildRollups(discrepancies), [discrepancies]);

  const groups = useMemo(() => {
    const m = new Map<string, DiscrepancyVM[]>();
    for (const d of discrepancies) {
      const k = groupKey(d, by);
      (m.get(k) ?? m.set(k, []).get(k)!).push(d);
    }
    // Within every group, surface high-severity rows first (regardless of the
    // active grouping) — severity_hint is the trustworthy risk signal on real
    // data where confidence scores are absent.
    for (const rows of m.values()) {
      rows.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
    }
    const entries = [...m.entries()];
    if (by === "severity_hint") {
      entries.sort(
        (a, b) => SEVERITY_ORDER[a[0] as Severity] - SEVERITY_ORDER[b[0] as Severity],
      );
    } else {
      entries.sort((a, b) => a[0].localeCompare(b[0]));
    }
    return entries;
  }, [discrepancies, by]);

  if (loading) return <p className="muted">Loading discrepancies…</p>;
  if (error) return <p className="error">{error}</p>;

  return (
    <div className="view">
      <header className="view__head">
        <h2>Discrepancy report</h2>
        <p className="muted">{discrepancies.length} rows · points vs. drawings, Floor 02</p>
      </header>

      {rollups.length > 0 && (
        <ul className="rollups">
          {rollups.map((r) => (
            <li key={r} className="rollup">{r}</li>
          ))}
        </ul>
      )}

      <div className="toolbar">
        <span className="muted small">Group by:</span>
        {(["severity_hint", "floor", "equipment_type"] as GroupBy[]).map((g) => (
          <button
            key={g}
            className={`chip${by === g ? " chip--active" : ""}`}
            onClick={() => setBy(g)}
          >
            {g.replace(/_/g, " ").replace(" hint", "")}
          </button>
        ))}
      </div>

      {groups.map(([key, items]) => (
        <section key={key} className="group">
          <h3 className="group__head">
            <span className={`sev sev--${by === "severity_hint" ? key : "none"}`}>{key}</span>
            <span className="muted small">{items.length} rows</span>
          </h3>
          <table className="grid">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Equipment</th>
                <th>Type</th>
                <th>Status</th>
                <th>Evidence</th>
                <th className="grid__actions">Decision</th>
              </tr>
            </thead>
            <tbody>
              {items.map((d) => (
                <tr key={d.key} className={d.severity === "high" ? "row--flagged" : undefined}>
                  <td><span className={`sev sev--${d.severity}`}>{d.severity}</span></td>
                  <td className="mono">{d.equipmentId}</td>
                  <td>{d.equipmentType}</td>
                  <td>
                    <span className="tag">{d.status.replace(/_/g, " ")}</span>
                    {d.resolvedFloor && (
                      <span className="tag tag--muted">→ floor {d.resolvedFloor}</span>
                    )}
                  </td>
                  <td className="evidence">
                    <span className={d.inPoints ? "ev ev--on" : "ev ev--off"}>points</span>
                    <span className={d.inDrawings ? "ev ev--on" : "ev ev--off"}>drawings</span>
                  </td>
                  <td className="grid__actions">
                    <ReviewActions
                      itemType="discrepancy"
                      itemKey={d.key}
                      editTitle={`Resolve ${d.equipmentId}`}
                      editFields={[
                        { key: "status", label: "Status", value: d.status, type: "select", options: DISCREPANCY_STATUSES },
                        { key: "severity", label: "Severity", value: d.severity, type: "select", options: SEVERITIES },
                        { key: "resolvedFloor", label: "Resolved floor", value: d.resolvedFloor ?? "" },
                      ]}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}
