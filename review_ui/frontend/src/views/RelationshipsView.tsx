import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useData } from "../session/DataContext";
import { ReviewActions } from "../components/ReviewActions";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { REF_TYPES } from "../lib/vocab";
import type { RelationshipEdgeVM } from "../types/viewModels";

const editFieldsFor = (e: RelationshipEdgeVM) => [
  { key: "parent", label: "Parent (served by)", value: e.parent },
  { key: "refType", label: "Ref type", value: e.refType, type: "select" as const, options: REF_TYPES },
];

/**
 * Relationship graph — AHU->VAV (airRef) / equipment->plant (waterRef) edges on
 * an interactive react-flow canvas. Drag node→node (onConnect) proposes a new
 * serving edge ("source serves target via airRef"); the proposal then appears in
 * the table below as a pending row the engineer approves/edits/rejects. Clicking
 * an edge selects it and surfaces its review controls. W4 documented 0 serving
 * edges, so today every terminal is an orphan awaiting an assignment.
 */
export function RelationshipsView() {
  const { relationships, loading, error } = useData();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [assigned, setAssigned] = useState<RelationshipEdgeVM[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  // Nodes depend only on the loaded data, so dragging positions survive edge edits.
  useEffect(() => {
    if (!relationships) return;
    const ids = new Set<string>();
    for (const e of relationships.edges) {
      ids.add(e.child);
      ids.add(e.parent);
    }
    for (const o of relationships.orphans) for (const n of o.nodes) ids.add(n);
    const orphanIds = new Set(relationships.orphans.flatMap((o) => o.nodes));
    setNodes(
      [...ids].map((id, i) => ({
        id,
        position: { x: 40 + (i % 4) * 200, y: 40 + Math.floor(i / 4) * 110 },
        data: { label: id },
        className: orphanIds.has(id) ? "rf-node--orphan" : undefined,
      })),
    );
  }, [relationships, setNodes]);

  // All edges = validated (from data) + engineer-proposed (assigned on the canvas).
  const allEdges = useMemo<RelationshipEdgeVM[]>(
    () => [...(relationships?.edges ?? []), ...assigned],
    [relationships, assigned],
  );

  useEffect(() => {
    setEdges(
      allEdges.map((e) => ({
        id: e.key,
        source: e.parent,
        target: e.child,
        label: e.refType,
        selected: e.key === selectedKey,
        animated: e.conflict,
        className: assigned.some((a) => a.key === e.key)
          ? "rf-edge--new"
          : e.conflict
            ? "rf-edge--conflict"
            : undefined,
      })),
    );
  }, [allEdges, assigned, selectedKey, setEdges]);

  const onConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target) return;
      const key = `${conn.target}|airRef|${conn.source}`;
      setAssigned((prev) =>
        prev.some((a) => a.key === key) || (relationships?.edges ?? []).some((e) => e.key === key)
          ? prev
          : [
              ...prev,
              {
                key,
                child: conn.target!,
                parent: conn.source!,
                refType: "airRef",
                confidence: null,
                conflict: false,
                conflictReason: null,
                sourceDrawing: null,
              },
            ],
      );
      setSelectedKey(key);
    },
    [relationships],
  );

  const selected = allEdges.find((e) => e.key === selectedKey) ?? null;

  if (loading) return <p className="muted">Loading relationships…</p>;
  if (error) return <p className="error">{error}</p>;
  if (!relationships) return <p className="muted">No relationship data.</p>;

  return (
    <div className="view">
      <header className="view__head">
        <h2>Relationship graph</h2>
        <p className="muted">
          {relationships.edges.length} validated · {assigned.length} proposed ·{" "}
          {relationships.orphans.length} orphan terminals · Floor 02
        </p>
      </header>

      <div className="note note--info">
        Drag from one node to another to propose a serving edge
        (<code>source serves target via airRef</code>); it appears below as a pending row.
        Click an edge to select it and act on it.
      </div>

      <div className="graph">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onEdgeClick={(_, edge) => setSelectedKey(edge.id)}
          onPaneClick={() => setSelectedKey(null)}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>

      {selected && (
        <div className="selected-edge">
          <span className="muted small">Selected edge</span>
          <span className="mono">{selected.child}</span>
          <span className="muted">← {selected.refType} ←</span>
          <span className="mono">{selected.parent}</span>
          <span className="modal__spacer" />
          <ReviewActions
            itemType="relationship"
            itemKey={selected.key}
            confidence={selected.confidence}
            editTitle={`Redraw ${selected.child}`}
            editFields={editFieldsFor(selected)}
          />
        </div>
      )}

      {allEdges.length === 0 ? (
        <p className="muted">
          No serving relationships yet — propose them by dragging on the canvas above.
        </p>
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th>Confidence</th>
              <th>Child</th>
              <th>Ref</th>
              <th>Parent</th>
              <th>Origin</th>
              <th className="grid__actions">Decision</th>
            </tr>
          </thead>
          <tbody>
            {allEdges.map((e) => {
              const proposed = assigned.some((a) => a.key === e.key);
              return (
                <tr
                  key={e.key}
                  className={[
                    e.key === selectedKey ? "row--selected" : "",
                    e.conflict ? "row--flagged" : "",
                  ].join(" ").trim() || undefined}
                  onClick={() => setSelectedKey(e.key)}
                >
                  <td><ConfidenceBadge confidence={e.confidence} /></td>
                  <td className="mono">{e.child}</td>
                  <td>{e.refType}</td>
                  <td className="mono">{e.parent}</td>
                  <td>
                    <span className={`tag ${proposed ? "" : "tag--muted"}`}>
                      {proposed ? "proposed" : "validated"}
                    </span>
                  </td>
                  <td className="grid__actions">
                    <ReviewActions
                      itemType="relationship"
                      itemKey={e.key}
                      confidence={e.confidence}
                      editTitle={`Redraw ${e.child}`}
                      editFields={editFieldsFor(e)}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {relationships.orphans.length > 0 && (
        <div className="orphans">
          <h3>Orphan terminals</h3>
          <ul>
            {relationships.orphans.map((o) => (
              <li key={o.nodes.join("-")} className="orphan">{o.message}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
