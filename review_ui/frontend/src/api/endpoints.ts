// HTTP endpoint paths for the W5 Review Agent API (Track B `review_api/app.py`).
// Paths/verbs are the stable part of the contract; field shapes are normalised
// in `adapter.ts`. Base URL + mock switch live in `client.ts`.

export const ENDPOINTS = {
  equipment: "/equipment",
  relationships: "/relationships",
  discrepancies: "/discrepancies",
  zones: "/zones",
  sessions: "/sessions",
  session: (id: string) => `/sessions/${id}`,
  sessionActions: (id: string) => `/sessions/${id}/actions`,
  sessionCommit: (id: string) => `/sessions/${id}/commit`,
} as const;
