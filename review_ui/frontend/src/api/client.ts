// Review Agent API client.
//
// Defaults to MOCK mode (no backend, no DB) so the UI is fully clickable while
// the W5 backend A->B merge is in flight. Flip to live HTTP by setting
// `VITE_USE_MOCKS=false` (and optionally `VITE_API_BASE_URL`) — see README.

import { ENDPOINTS } from "./endpoints";
import {
  toDiscrepancyVM,
  toEquipmentVM,
  toRelationshipsVM,
  toSessionVM,
  toZoneVM,
} from "./adapter";
import {
  FLOOR,
  PROPERTY_ID,
  mockDiscrepancies,
  mockEquipment,
  mockRelationships,
  mockZones,
} from "./fixtures";
import type { RawSession } from "./raw";
import type {
  DiscrepancyVM,
  EquipmentVM,
  ItemType,
  RelationshipsVM,
  SessionVM,
  ZoneVM,
} from "../types/viewModels";

const API_BASE: string =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export const USE_MOCKS: boolean =
  import.meta.env.VITE_USE_MOCKS !== "false"; // mocks unless explicitly disabled

export interface ActionInput {
  itemType: ItemType;
  itemKey: string;
  action: "approve" | "edit" | "reject";
  payload?: Record<string, unknown> | null;
  confidence?: number | null;
  reviewer?: string | null;
  reason?: string | null;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} -> ${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

async function deleteJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`DELETE ${path} -> ${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

// --------------------------------------------------------------------------- //
// In-memory mock session (records decisions so counts stay consistent on
// re-decision; everything is lost on reload, exactly like the real fake store).
// --------------------------------------------------------------------------- //
let mockSession: RawSession | null = null;
const mockDecisions = new Map<string, ActionInput["action"]>();

function recountMock(): void {
  if (!mockSession) return;
  let approved = 0;
  let rejected = 0;
  for (const action of mockDecisions.values()) {
    if (action === "reject") rejected += 1;
    else approved += 1; // approve + edit both produce a production write
  }
  mockSession.n_approved = approved;
  mockSession.n_rejected = rejected;
  // pending = items still awaiting a decision; the UI computes the true figure
  // from total items, so we only need a non-negative floor here.
  mockSession.n_pending = Math.max(0, (mockSession.n_pending ?? 0));
}

// --------------------------------------------------------------------------- //
// Reads
// --------------------------------------------------------------------------- //
export async function listEquipment(): Promise<EquipmentVM[]> {
  const raw = USE_MOCKS ? mockEquipment : await getJSON<unknown[]>(ENDPOINTS.equipment);
  return (raw as Parameters<typeof toEquipmentVM>[0][]).map(toEquipmentVM);
}

export async function listZones(): Promise<ZoneVM[]> {
  const raw = USE_MOCKS ? mockZones : await getJSON<unknown[]>(ENDPOINTS.zones);
  return (raw as Parameters<typeof toZoneVM>[0][]).map(toZoneVM);
}

export async function listDiscrepancies(): Promise<DiscrepancyVM[]> {
  const raw = USE_MOCKS
    ? mockDiscrepancies
    : (await getJSON<{ items?: unknown[] }>(ENDPOINTS.discrepancies)).items ?? [];
  return (raw as Parameters<typeof toDiscrepancyVM>[0][]).map(toDiscrepancyVM);
}

export async function listRelationships(): Promise<RelationshipsVM> {
  const raw = USE_MOCKS
    ? mockRelationships
    : await getJSON<Parameters<typeof toRelationshipsVM>[0]>(ENDPOINTS.relationships);
  return toRelationshipsVM(raw);
}

// --------------------------------------------------------------------------- //
// Session / write path
// --------------------------------------------------------------------------- //
export async function openSession(reviewer?: string): Promise<SessionVM> {
  if (USE_MOCKS) {
    mockSession = {
      session_id: crypto.randomUUID(),
      property_id: PROPERTY_ID,
      floor: FLOOR,
      status: "open",
      n_pending: 0,
      n_approved: 0,
      n_rejected: 0,
    };
    mockDecisions.clear();
    return toSessionVM(mockSession);
  }
  const raw = await postJSON<RawSession>(ENDPOINTS.sessions, {
    property_id: PROPERTY_ID,
    floor: FLOOR,
    reviewer: reviewer ?? null,
  });
  return toSessionVM(raw);
}

export async function recordAction(
  sessionId: string,
  input: ActionInput,
): Promise<SessionVM> {
  if (USE_MOCKS) {
    if (!mockSession) throw new Error("no open session");
    mockDecisions.set(`${input.itemType}:${input.itemKey}`, input.action);
    recountMock();
    return toSessionVM(mockSession);
  }
  await postJSON(ENDPOINTS.sessionActions(sessionId), {
    item_type: input.itemType,
    item_key: input.itemKey,
    action: input.action,
    payload: input.payload ?? null,
    confidence: input.confidence ?? null,
    reviewer: input.reviewer ?? null,
    reason: input.reason ?? null,
  });
  return getSession(sessionId);
}

/** Clear a single uncommitted decision in the active store. */
export async function clearAction(
  sessionId: string,
  itemType: ItemType,
  itemKey: string,
): Promise<SessionVM> {
  if (USE_MOCKS) {
    if (!mockSession) throw new Error("no open session");
    mockDecisions.delete(`${itemType}:${itemKey}`);
    recountMock();
    return toSessionVM(mockSession);
  }
  const raw = await deleteJSON<RawSession>(
    ENDPOINTS.sessionAction(sessionId, itemType, itemKey),
  );
  return toSessionVM(raw);
}

/** Clear every uncommitted decision in the current batch. */
export async function clearAllActions(sessionId: string): Promise<SessionVM> {
  if (USE_MOCKS) {
    if (!mockSession) throw new Error("no open session");
    mockDecisions.clear();
    recountMock();
    return toSessionVM(mockSession);
  }
  return toSessionVM(
    await deleteJSON<RawSession>(ENDPOINTS.sessionActions(sessionId)),
  );
}

export async function getSession(sessionId: string): Promise<SessionVM> {
  if (USE_MOCKS) {
    if (!mockSession) throw new Error("no open session");
    return toSessionVM(mockSession);
  }
  return toSessionVM(await getJSON<RawSession>(ENDPOINTS.session(sessionId)));
}

export async function commitSession(sessionId: string): Promise<SessionVM> {
  if (USE_MOCKS) {
    if (!mockSession) throw new Error("no open session");
    mockSession.status = "committed";
    return toSessionVM(mockSession);
  }
  await postJSON(ENDPOINTS.sessionCommit(sessionId), {});
  return getSession(sessionId);
}

/** Stable natural key for tracking a per-item decision in the UI. */
export function decisionKey(itemType: ItemType, itemKey: string): string {
  return `${itemType}:${itemKey}`;
}
