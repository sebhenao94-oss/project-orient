# ORIENT Review Agent — Frontend (W6)

React + TypeScript + Vite frontend for the human review agent. It renders the four
W6 review views over the W5 `review_api` backend:

1. **Equipment** — approve / edit / reject, sorted confidence-ascending (low first)
2. **Relationships** — react-flow graph of AHU→VAV / equipment→plant edges + orphan terminals
3. **Discrepancies** — W4 gap rows grouped by severity / floor / equipment type, with rollups
4. **Zones** — confirm / correct each zone's orientation (data lands in W7)

Cross-cutting: confidence shown on every item with a low-confidence (<0.75) flag, a
session progress bar (approved / pending / rejected), and a **commit button — the only
path to the production DB**.

## Run

```bash
npm install
npm run dev      # http://localhost:5173
```

By default it runs on **mock data** (the committed W4 snapshots, in `src/api/fixtures.ts`)
— no backend, no database, no credentials. The whole UI is clickable offline.

## Point it at the live backend

When the W5 backend A→B merge lands and `uvicorn review_api.app:app` is running:

```bash
# review_ui/frontend/.env.local
VITE_USE_MOCKS=false
VITE_API_BASE_URL=http://127.0.0.1:8000
```

(The backend needs CORS enabled for the dev origin — that's wired in at convergence.)

## Architecture — built to survive the contract merge

The backend contract (`review_api/contracts.py`) is still being reconciled, so the UI
is decoupled from it:

- `src/types/viewModels.ts` — the types the UI displays (**owned here**, not mirrored)
- `src/api/raw.ts` — tolerant types for the raw backend JSON
- `src/api/adapter.ts` — **the only backend-aware module**; maps raw JSON → view models
- `src/api/client.ts` — reads + session/commit, with the mock/live switch
- `src/api/fixtures.ts` — mock data mirroring `data/snapshots/w04/*`

When the contract is final, reconcile field names in `adapter.ts` (and tighten `raw.ts`);
every component stays put.

## Layout

```
src/
  api/        endpoints, raw types, adapter, client, fixtures
  components/ ConfidenceBadge, ReviewActions, SessionBar, TabNav
  lib/        review.ts (0.75 threshold, confidence-asc sort)
  session/    DataContext (loads the 4 datasets), SessionContext (decisions + commit)
  types/      viewModels.ts
  views/      Equipment, Relationships, Discrepancies, Zones
```

## Status (W6)

- Done: scaffold, app shell, session/commit flow, shared UX primitives, Equipment +
  Zones views fully built, Discrepancies grouped with rollups, Relationships graph v0.
- Workstream B (design): the interactive confirm/redraw edge interaction for the
  relationship graph.
- After the merge: point the adapter at real JSON, enable CORS, swap `REVIEW_STORE=postgres`.
