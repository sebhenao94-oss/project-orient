# ORIENT Review Agent — Frontend (W6)

React + TypeScript + Vite frontend for the human review agent. It renders the four
W6 review views over the W5 `review_api` backend:

1. **Equipment** — approve / edit / reject, sorted confidence-ascending (low first)
2. **Relationships** — react-flow graph of AHU→VAV / equipment→plant edges + orphan terminals
3. **Discrepancies** — W4 gap rows grouped by severity / floor / equipment type, with rollups
4. **Zones** — explicit placeholder; no zone-orientation dataset is shipped

Cross-cutting: confidence shown on every item with a low-confidence (<0.75) flag, a
session progress bar (approved / pending / rejected), and a **commit button — the only
path to the production DB**.

## Run

```bash
npm ci
npm run dev      # http://localhost:5173
```

Use Node 20.19+ or 22.12+; the requirement is enforced by `package.json`.

By default it calls the local review API. Use the API's `REVIEW_STORE=fake` backend for the offline W6 snapshot path: no database credentials, but still the same HTTP contract the Postgres path uses.

## Point it at the live backend

When `uvicorn review_api.app:app` is running:

```bash
# review_ui/frontend/.env.local`r`nVITE_API_BASE_URL=http://127.0.0.1:8000
```

(The backend already enables CORS for the documented development origin.)

Set `VITE_USE_MOCKS=true` only for isolated frontend checks. Those browser-only
fixtures are not the acceptance dataset.

## Architecture

The UI keeps a small adapter boundary around the backend contract:

- `src/types/viewModels.ts` — the types the UI displays (**owned here**, not mirrored)
- `src/api/raw.ts` — tolerant types for the raw backend JSON
- `src/api/adapter.ts` — **the only backend-aware module**; maps raw JSON → view models
- `src/api/client.ts` - reads + session/commit, with an explicit mock switch
- `src/api/fixtures.ts` - isolated UI fixtures, not the acceptance dataset

Backend field-name changes should be reconciled in `adapter.ts` (and tightened in
`raw.ts`) so view components remain stable.

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

## Status (W6 closeout)

- Implemented: app shell, fake/live API adapter, session commit/clear flow,
  Equipment actions, discrepancy rollups, and interactive relationship review.
- The Zones tab deliberately reports that no zone-orientation output is shipped;
  it must not be interpreted as a completed extraction stage.
- The live data path uses `REVIEW_STORE=postgres`; it still requires the documented database-admin grant, an authentication/authorization decision before network exposure, and a real review-session acceptance run.
