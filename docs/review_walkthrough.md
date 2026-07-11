# Human Review Board — Walkthrough & Video Script

Reviewer guide for the ORIENT review agent, plus the recording script for the
walkthrough video (team-lead final-checklist item 5a) and the live-database
runbook. The board is the **mandatory human gate**: nothing reaches the
production database except through an explicit review-session commit.

## 1. Starting the board

Two backends, selected by the `REVIEW_STORE` env var:

| Mode | Data | Writes go to |
|---|---|---|
| `fake` (default) | committed `data/snapshots/w06/` | in-memory only — safe for demos/training |
| `postgres` | same snapshots for review items | live `review_session` / `review_action` / `correction_log` + production tables on commit |

```powershell
# backend (terminal 1)
$env:REVIEW_STORE = "fake"          # or "postgres" after the runbook in §6
py -m uvicorn review_api.app:app --port 8000

# frontend (terminal 2)
cd review_ui\frontend
npm run dev                          # http://localhost:5173
# talk to the real backend instead of UI mocks: VITE_USE_MOCKS=false in .env.local
```

## 2. Reading the screen

- **Session bar (top right):** the open session id, a progress bar, and live
  `approved / pending / rejected` counts. **Commit session** is the only path
  to the production DB. A committed batch locks; undecided items stay
  actionable in a later session (partial commits are supported).
- **Four tabs:** Equipment, Relationships, Discrepancies, Zones (zones is a
  placeholder — zone orientation was descoped with point classification).

## 3. How to read flags and reasons

Every item carries `review_required` and a human-readable `review_reason`
saying **which pipeline stage flagged it and why**. The lists sort flagged /
low-confidence items first, so the top of each list is where attention goes.

Common reason patterns and what they mean:

| Reason looks like | Origin | What the reviewer decides |
|---|---|---|
| `present in BMS topics but absent from drawing evidence` | normalization gap (`topics_only`) | Does the unit exist? Approve (trust point evidence) or reject (stale/mislabeled topics). |
| `extracted from drawings but absent from BMS topics` | normalization gap (`drawing_only`) | Real unmonitored unit → approve; OCR misread (e.g. `DAWNV_2_9` for `OAVAV_2_09`) → reject with that reason. |
| `reheat source assumed hot-water … confirm against VAV-RH-ELEC` | vocabulary subtype assumption | Confirm HW or edit the type to the ELEC variant. |
| `vision second pass CONFIRMED <type>` | topics parser vision pass | Two sources agree — quick approve. |
| `vision second pass CONFLICT: sees X, topics say Y` | topics parser vision pass | Genuine disagreement — inspect the screenshot evidence. |
| `airRef <parent> inferred but unconfirmed: …` / `airRef conflict: …` | relationship extraction | Confirm or redraw the edge in the Relationships view. |
| `floor digit inferred from inline token '02A'` | canonical naming | Sanity-check the name; usually approve. |

**Evidence column:** chips show which sources contributed (`topics` /
`drawings`) with the raw labels from each side; canonical equipment rows also
carry `source_files` (every drawing the unit was read from) and the inferred
`airRef`/`waterRef`/`spaceRef` parents.

**Discrepancies tab** is evidence, not a decision queue: rollup headlines
("Floor 2: 4 FCUs missing from drawings") grouped by severity / floor /
equipment type point you at the equipment rows to act on. Severity hints:
AHU/plant gaps = high, terminal-unit gaps = medium, ID-only mismatches = low.

## 4. Making decisions

- **Approve** — the item is correct; it will be written to the production
  tables at commit.
- **Edit** — correct with changes (type, name, ref); a **reason is required**.
  The edit is written to production at commit **and** logged in
  `correction_log` so the pipeline's few-shot pool learns from it.
- **Reject** — not real / misread; a **reason is required**. Nothing goes to
  production; the rejection is logged in `correction_log` with the original
  value and your reason.

One live decision per item per session — acting again replaces the earlier
decision until commit.

## 5. Committing and the upload script

Commit from the session bar, or operationally via the upload script:

```powershell
py scripts\upload_reviewed.py check                       # is the DB reachable + tables present?
py scripts\upload_reviewed.py list                        # sessions and their progress
py scripts\upload_reviewed.py commit <session-id> --export-fewshot
```

`commit` applies the session atomically — approvals/edits upsert
`equipment_details` (and relationship refs), rejections land in
`correction_log` — and `--export-fewshot` then appends new corrections to the
few-shot pool (`data/extractions/w05/correction_fewshot_pool.jsonl`), which
future pipeline runs consume. That closes the loop: **validated equipment flows back
into the pipeline instead of staying in the review layer.**

## 6. Live-database runbook (one-time cutover)

On a machine with database access (VPN/SSH tunnel as applicable):

1. Fill `DB_HOST` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_PORT` in `.env`
   (never commit real values). Start the SSH tunnel if the DB is reached
   through one.
2. Install the driver: `py -m pip install "psycopg[binary]"` (behind a
   TLS-intercepting antivirus/proxy, add `--cert <ca-bundle.pem>`).
3. `py scripts\upload_reviewed.py check` — expect `READY`. If the review
   tables are missing: `py scripts\upload_reviewed.py create-tables`
   (requires the grants in `docs/w5_database_admin_request.md`).
4. Start the backend with `REVIEW_STORE=postgres`, the frontend with
   `VITE_USE_MOCKS=false`, and run the review pass (§3–§4).
5. Commit via the UI or `upload_reviewed.py commit <id> --export-fewshot`.

## 7. Video recording script (~5 minutes)

1. **Open (20s).** "This is the ORIENT human review board — the mandatory gate
   between the LLM pipeline and the production database. Nothing is written
   without an engineer's explicit approval and a session commit."
2. **Session bar (30s).** Point out the open session id and the
   approved/pending/rejected progress. "A session is one review sitting;
   committed batches lock, everything else stays actionable."
3. **Equipment tab (90s).** Show the flagged-first sort. Walk one gap row
   ("present in topics but absent from drawings") — read the evidence chips
   and raw labels, approve it. Walk one subtype row (VAVRH → confirm HW vs
   edit to ELEC). Reject `DAWNV_2_9` with the reason "OCR misread of
   OAVAV_2_09" to show a reasoned rejection.
4. **Relationships tab (60s).** Show the graph, a confirmed airRef edge with
   its linked-widget evidence, and one conflicted edge. Drag a terminal onto
   its AHU to propose an edge.
5. **Discrepancies tab (40s).** Show the rollup headlines and severity
   grouping; explain these are evidence pointing at equipment decisions, not
   separate decisions.
6. **Commit (40s).** Press **Commit session**, show the counts move, then run
   `upload_reviewed.py list` and `commit … --export-fewshot` in a terminal to
   show the operational path and the correction flowing to the few-shot pool.
7. **Close (20s).** "Approved equipment is now in `equipment_details`;
   rejections are in `correction_log` and feed the few-shot examples the next
   pipeline run uses — the review loop makes the pipeline better over time."
