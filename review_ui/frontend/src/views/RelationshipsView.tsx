import { useCallback, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useData } from "../session/DataContext";
import { useSession } from "../session/SessionContext";
import { ReviewActions } from "../components/ReviewActions";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { REF_TYPES } from "../lib/vocab";

/**
 * Relationship graph — AHU->VAV (airRef) and equipment->plant (waterRef) edges
 * on an interactive react-flow canvas. The redraw/assign interaction follows the
 * canonical react-flow pattern: drag from one node to another (onConnect ->
 * addEdge) to assert "<source> serves <target> via airRef" — that gets recorded
 * as a review decision. W4 documented 0 serving edges, so today every terminal
 * is an orphan awaiting an AHU parent; this is exactly the assignment the graph
 * lets the engineer make.
 */
export function RelationshipsView() {
  const { relationships, loading, error } = useData();
  const { decide } = useSession();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

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
    setEdges(
      relationships.edges.map((e) => ({
        id: e.key,
        source: e.parent,
        target: e.child,
        label: e.refType,
        animated: e.conflict,
        className: e.conflict ? "rf-edge--conflict" : undefined,
      })),
    );
  }, [relationships, setNodes, setEdges]);

  const onConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target) return;
      const key = `${conn.target}|airRef|${conn.source}`;
      setEdges((eds) => addEdge({ ...conn, id: key, label: "airRef", className: "rf-edge--new" }, eds));
      void decide({
        itemType: "relationship",
        itemKey: key,
        action: "edit",
        payload: { child: conn.target, parent: conn.source, refType: "airRef" },
        reason: "Assigned via relationship graph",
      });
    },
    [decide, setEdges],
  );

  if (loading) return <p className="muted">Loading relationships…</p>;
  if (error) return <p className="error">{error}</p>;
  if (!relationships) return <p className="muted">No relationship data.</p>;

  return (
    <div className="view">
      <header className="view__head">
        <h2>Relationship graph</h2>
        <p className="muted">
          {relationships.edges.length} validated edges · {relationships.orphans.length} orphan terminals · Floor 02
        </p>
      </header>

      <div className="note note--info">
        Drag from one node to another to assign a serving relationship
        (<code>source serves target via airRef</code>) — it's recorded as a review
        decision. Existing edges can be approved/rejected in the table below.
      </div>

      <div className="graph">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>

      {relationships.edges.length === 0 ? (
        <p className="muted">
          No serving relationships were documented in W4 — assign them on the canvas above.
        </p>
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th>Confidence</th>
              <th>Child</th>
              <th>Ref</th>
              <th>Parent</th>
              <th className="grid__actions">Decision</th>
            </tr>
          </thead>
          <tbody>
            {relationships.edges.map((e) => (
              <tr key={e.key} className={e.conflict ? "row--flagged" : undefined}>
                <td><ConfidenceBadge confidence={e.confidence} /></td>
                <td className="mono">{e.child}</td>
                <td>{e.refType}</td>
                <td className="mono">{e.parent}</td>
                <td className="grid__actions">
                  <ReviewActions
                    itemType="relationship"
                    itemKey={e.key}
                    confidence={e.confidence}
                    editTitle={`Redraw ${e.child}`}
                    editFields={[
                      { key: "parent", label: "Parent (served by)", value: e.parent },
                      { key: "refType", label: "Ref type", value: e.refType, type: "select", options: REF_TYPES },
                    ]}
                  />
                </td>
              </tr>
            ))}
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
