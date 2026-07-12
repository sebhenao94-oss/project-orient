# Project ORIENT

**LLM-assisted onboarding of building HVAC systems: from BMS screenshots and
mechanical drawings to a clean, human-verified equipment and relationship
database for Fault Detection & Diagnostics (FDD).**

ORIENT ingests the messy artifacts every building actually has — BMS graphics
screenshots, mechanical floor plans, and raw point-name dumps — and produces a
reconciled, provenance-rich HVAC equipment inventory with Haystack-style
relationship refs. A vision/text LLM pipeline does the extraction; a human
review board is the only path into the production database. **Nothing is
written to production without an engineer's explicit, reasoned approval.**

> **Status: Part I complete for Floor 02** (Summer 2026, Team 4). The full
> pipeline and review tooling are implemented and covered by a 617-test
> offline suite. Live S3/model/Postgres acceptance, the reviewer walkthrough
> recording, and additional-floor runs are documented operator runbooks, not
> unfinished build work. See [Project status](#project-status).

## Contents

- [How it works](#how-it-works)
- [Design principles](#design-principles)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Running the pipeline](#running-the-pipeline)
- [The human review board](#the-human-review-board)
- [Outputs & data model](#outputs--data-model)
- [Metrics & cost](#metrics--cost)
- [Testing](#testing)
- [Project status](#project-status)
- [Documentation](#documentation)

## How it works

```text
      S3 bucket ──► downloads/<floor>/                BMS topics (Postgres, read-only)
                          │                                      │
              [1] Ingestion                          [2b] Topics → equipment
          quality gate · 300 DPI PDF→PNG          LLM parser (no fixed path-shape
          raw S3 upload · manifests               assumption) · deterministic parse
                          │                       as validation · vision second pass
              [2a] Drawings → equipment                          │
          vision LLM, few-shot prompt                            │
          two-tier ingestion router                              │
          full-res tiled drawing path                            │
                          └────────────────┬─────────────────────┘
                                           ▼
              [3] Normalization · deduplication · discrepancy (gap) report
                  canonical {Type}_{floor}-{unit} naming · source traceability
                                           ▼
              [4] Relationships — BMS graphics linked widgets
                  airRef / chilledWaterRef / hotWaterRef with evidence
                                           ▼
              [5] Human review board  (FastAPI + React)
                  flags & reasons · approve / edit / reject · session commit
                                           ▼
          Production DB (equipment_details + refs)     correction_log ──► few-shot pool
                                                       (reviewer edits improve the
                                                        next pipeline run)
```

Two independent evidence sources — what the point names imply exists, and what
the drawings/graphics show — are extracted separately, reconciled on a
separator/zero-padding-insensitive canonical key, and every disagreement is
emitted as a review-flagged discrepancy rather than silently resolved.

## Design principles

- **Review-gated writes.** The production DB is the verified store, not the
  extraction scratchpad. Only an explicit review-session commit writes to it;
  rejections and edits are logged with reasons and feed the few-shot pool.
- **Flags, not silent fixes.** Ambiguous types, contested floors, OCR
  misreads, and conflicting relationship evidence are preserved and routed to
  review with a human-readable reason naming the originating stage.
- **Model selection at ingestion, not threshold tuning.** Per-item confidence
  cannot catch omissions, so large mechanical drawings route up front to the
  configured capable model through full-resolution tiling. Screenshots stay on
  the configured lower-cost model. The separate L1–L4 escalation ladder remains
  an experimental library path; the documented CLI uses this explicit two-tier
  route so its model and cost behavior are predictable.
- **Provider-neutral seams.** All inference goes through an OpenAI-compatible
  client boundary; the backend swapped twice (Qwen/Colab → Anthropic Claude)
  with zero changes to extraction or parsing code. The review API is likewise
  written once against a `ReviewStore` protocol with in-memory and Postgres
  implementations.
- **Crash-safe, metered runs.** Extraction runs checkpoint per image (a
  restart re-sends only incomplete work) and every run emits token/cost
  metrics per model.
- **Git is the version history.** One current-best prompt set, iterated in
  place — no `v1/v2/v3` file proliferation.

## Repository layout

```text
pipeline/                  the Python pipeline (ingestion → extraction → normalization
                           → relationships → review store; plus cost/metrics, checkpointing,
                           two-tier CLI routing, experimental escalation, model clients)
prompts/                   current-best prompt packages (equipment extraction, relationship
                           graphics) + the generated equipment-type context
equipments_point_types/    supervisor classification library (types, point types, equip tags)
review_api/                FastAPI review backend (contracts seam, fake + Postgres stores)
review_ui/frontend/        React + TypeScript review frontend (Vite, react-flow)
scripts/                   populate_downloads.py (S3 sync) · upload_reviewed.py (DB handoff)
data/snapshots/            versioned, committed pipeline outputs (w03/w04/w06)
downloads/<floor>/         standard input location for source files (synced from S3)
outputs/<floor>/           per-floor run outputs (snapshots, run JSONL, metrics, checkpoints)
docs/                      findings, runbooks, walkthrough, struggles report, build history
tests/                     offline unit/integration tests (no network, AWS, or DB required)
config/.env.example        documented template for every configuration variable
```

## Getting started

### Prerequisites

- **Python 3.8+** (`py` launcher on Windows)
- **Node 20.19+ or 22.12+** (review frontend only; required by Vite 8)
- **Poppler** on `PATH` (PDF → image conversion via `pdf2image`)
- AWS credentials (temporary MFA session) for S3 access; an **Anthropic API
  key** for live extraction; Postgres access for the topics export and the
  live review store (read paths work without either — see below)

### Install

```powershell
py -m pip install -r requirements.txt
cd review_ui\frontend; npm ci             # frontend only; uses package-lock.json
```

### Configure

```powershell
Copy-Item config\.env.example .env
```

`config/.env.example` documents every variable: S3 bucket/prefixes, DB
connection, ingestion quality thresholds, LLM provider/model/limits. Two
rules:

- **Never commit `.env`** or any credential (it is gitignored).
- Keep AWS access keys in your temporary shell session (MFA), not in `.env`.

Most commands below run **offline by default**: dry-run modes, the fake review store, and the committed snapshots mean no credentials are needed until you opt into a live call. Networked opt-ins are explicit: `--from-s3`, `--run-live`, `--upload`, and `REVIEW_STORE=postgres`.

## Running the pipeline

### 1 · Sync inputs

```powershell
python scripts/populate_downloads.py --floor Floor_2 --from-s3          # pull new/changed bucket files
python scripts/populate_downloads.py --floor Floor_2 --from-s3 --check  # report only; exit 1 if new files
```

Source files land in `downloads/<floor>/`, so every command below runs
unmodified on any machine.

### 2 · Ingestion (Stage 1)

```powershell
py -m pipeline.run "downloads\Floor_2" `
  --work-dir outputs\Floor_2\ingestion `
  --raw-prefix Team-4/raw/                         # add --upload for real S3 writes
```

Discovers PNG/JPG/PDF/DWG sources, captures SHA-256 provenance, converts PDFs
to 300 DPI pages, applies orientation-aware quality gates (configurable via
`INGESTION_*` env vars), and plans/performs raw S3 preservation. Stage 1 writes
`outputs\Floor_2\ingestion\prepared_image_records.jsonl`; this is the
validated handoff that preserves the original PDF filename, SHA-256, and page
number for Stage 2.

### 3 · Equipment from drawings & screenshots (Stage 2a)

```powershell
py -m pipeline.extraction extract `
  --prepared-records-manifest outputs\Floor_2\ingestion\prepared_image_records.jsonl `
  --example-image-dir downloads\Floor_2 `
  --property-id "b470b97b-4ea7-481c-97b7-22a81a219587" `
  --property-name "msa_orient_building_1" `
  --floor Floor_02 --snapshot-version w06 `
  --output-dir outputs\Floor_2 `
  --snapshot-path outputs\Floor_2\drawing_equipment_floor_02.csv `
  --drawing-model claude-opus-4-8 `
  --run-live
```

Few-shot vision extraction with strict schema validation. Built in:

- **Stage contract** — the default command consumes Stage 1's exact prepared
  record manifest, including PDF lineage. `--input-dir` remains available for
  deliberate direct-image runs, but it cannot reconstruct original PDF
  provenance from loose page images.

- **Simplified type context** — the extractor reads the type-names-only
  classification list (`prompts/equipment_type_context.md`; regenerate with
  `py -m pipeline.generate_equipment_type_context --simple`).
- **Checkpointing** — `outputs/<floor>/extraction_checkpoint.jsonl` records
  every completed image; a crash or re-run re-sends only incomplete/failed
  images. Changing the prompt or model invalidates old entries automatically.
- **Completeness gate** — eligible sources that return an empty equipment list,
  fail, or are skipped remain incomplete. Artifacts and metrics are written for
  diagnosis, then the command exits nonzero; `--allow-incomplete` is reserved
  for explicit partial pilots.
- **Reviewer feedback** — when
  `data/extractions/w05/correction_fewshot_pool.jsonl` exists, allowlisted
  equipment label/type corrections are appended to the prompt as data. Use
  `--no-correction-pool` only for a controlled comparison.
- **Two-tier routing & tiling** — records above the documented drawing-size
  threshold route to `--drawing-model` at full resolution through overlapping
  tiles; screenshots use `--model`. Use `--flat` for an intentional single-model
  A/B run without drawing tiling. Pixel count is an ingestion heuristic, not a
  claim that semantic drawing density has been measured.
- **Hybrid batch mode** — `--batch` sends screenshots through the Anthropic
  Message Batches API. Drawings cannot be dynamically tiled in that API, so the
  same invocation runs them realtime on `--drawing-model` and prints the split before any drawing requests. Run metrics still aggregate both paths. Native provider batch IDs are not yet persisted for mid-poll resume; use the per-image checkpoint after a completed batch result, or run realtime when interruption recovery is more important than batch discount.

### 4 · Equipment from BMS topics (Stage 2b)

```powershell
py -m pipeline.topics_parser --topics-csv <topics.csv> `
  --output-path outputs\Floor_2\topics_equipment_floor_02.csv `
  --property-id "b470b97b-4ea7-481c-97b7-22a81a219587" --property-name "msa_orient_building_1" `
  --floor-prefix Floor_02 --run-live `
  --vision-escalate-dir downloads\Floor_2 --example-image-dir downloads\Floor_2
```

An LLM groups raw topic names into equipment units with no fixed
`<floor>/<equipment>/<point>` assumption; the deterministic path-parse runs
only as a validation cross-check. Units the parser flags get a **vision second
pass** on their source screenshot before falling back to human review.

### 5 · Normalization, dedup & discrepancy report (Stage 3)

```powershell
py -m pipeline.normalization `
  --topics-path outputs\Floor_2\topics_equipment_floor_02.csv `
  --overwrite                                # consume the LLM-primary topics artifact
py -m pipeline.discrepancy                   # canonical list + brief-format gap report + ref columns
py -m pipeline.graph_validator --overwrite   # validates the current W06 graph; no live calls
```

Normalization accepts both the LLM-parser schema above and the legacy
deterministic W3 snapshot schema. Upstream topic and drawing review flags and
reasons are preserved; a matched unit cannot become settled while either source
still marks it ambiguous. Graph validation resolves canonical/topic/drawing
label variants using the normalization match key, but never accepts conflicted
or unresolved endpoints. Its default W06 report intentionally exits nonzero
while canonical terminals remain orphaned or candidate parents still await
review; inspect `data\snapshots\w06\graph_validation_floor_02.json` for the
actionable findings.

### 6 · Relationships (Stage 4)

```powershell
py -m pipeline.graphics_relationships --screenshots-dir downloads\Floor_2 --run-live `
  --evidence-csv-out outputs\Floor_2\relationship_evidence_floor_02.csv `
  --output-json outputs\Floor_2\relationships_floor_02.json
```

The BMS graphic pages embed the serving topology as linked equipment widgets;
reading them recovers `airRef` / `chilledWaterRef` / `hotWaterRef` edges with
per-edge evidence and confidence (44 candidate edges on Floor 02, vs. 1 from
floor-plan geometry — see
[`docs/relationship_graphics_findings.md`](docs/relationship_graphics_findings.md)).

## The human review board

```powershell
# backend — fake store by default (no DB/credentials); REVIEW_STORE=postgres for live
py -m uvicorn review_api.app:app --reload     # OpenAPI docs at http://127.0.0.1:8000/docs

# frontend
cd review_ui\frontend; npm run dev            # http://localhost:5173
# live backend instead of UI mocks: set VITE_USE_MOCKS=false in review_ui\frontend\.env.local
```

Four views — **Equipment** (approve/edit/reject, flagged items first),
**Relationships** (interactive react-flow graph; drag to propose an edge),
**Discrepancies** (gap report with rollup headlines, grouped by severity /
floor / type), **Zones** (placeholder; descoped) — plus a session progress bar
and partial (flush-and-continue) commits.

Every item carries `review_required` and a reason naming the stage that
flagged it. Edits and rejections require a reason and are recorded in
`correction_log`. The outbox exporter appends those decisions to the local
few-shot pool; the next equipment-extraction run consumes its allowlisted
label/type fields by default, and its content participates in the checkpoint
fingerprint.

Pushing reviewed data to the database:

```powershell
py scripts\upload_reviewed.py check                        # connectivity + review-table diagnostics
py scripts\upload_reviewed.py create-tables                # idempotent DDL (needs admin grant — see below)
py scripts\upload_reviewed.py list                         # sessions + progress
py scripts\upload_reviewed.py commit <session-id> --export-fewshot
```

`commit` is atomic: approvals/edits upsert the production tables, rejections
land in `correction_log`, and `--export-fewshot` appends new corrections to
the few-shot pool. One ops prerequisite: the review tables require a one-time
DDL + grant by a database admin
([`docs/w5_database_admin_request.md`](docs/w5_database_admin_request.md));
the full reviewer guide, live-DB runbook, and walkthrough-video script are in
[`docs/review_walkthrough.md`](docs/review_walkthrough.md).

## Outputs & data model

- **Canonical naming:** one public identity per unit,
  `{Type}_{floor}-{unit}` zero-padded (`AHU_2-01`, `VAV-RH-HW_2-01`),
  matching the database's worked example.
- **Traceability on every canonical row:** `in_topics` / `in_drawings` flags,
  the raw label from each source, `source_files` (every drawing the unit was
  read from, e.g. `ahu_02c.png;Floor_2A.pdf`), and `airRef` /
  `chilledWaterRef` / `hotWaterRef` / `condenserWaterRef` / `spaceRef` columns
  filled from inferred relationships (conflicting evidence routes to review
  instead of filling the column).
- **Discrepancy report** in the brief-mandated schema, keyed by
  `(building, floor, equipment_type, equipment_id)` with
  `in_points / in_drawings / status / evidence / severity_hint`.
- **Provenance-first artifacts:** raw run JSONL preserves image-level model responses and failures with SHA-256 source identity; successful tiled drawings retain the tile responses used to build the union, while malformed failure payloads may be truncated in the error field for artifact size. Committed snapshots under `data/snapshots/` are immutable evidence; per-floor working outputs live in `outputs/<floor>/`.

## Metrics & cost

Every LLM call site records token usage into a run-scoped recorder; each run
writes `run_metrics.json` — tokens and estimated cost per model, run totals,
wall time, and confident vs. review-flagged item counts. Counts describe raw
model output before cross-source deduplication. Historical Floor-02 development
runs used a capped team API key ($20/month) and recorded **~$0.35** of spend;
the audit branch has not repeated those paid calls. Projections and assumptions:
[`docs/cost_estimate.md`](docs/cost_estimate.md).

## Testing

```powershell
py -m unittest discover tests          # offline only — no network, AWS, or DB
cd review_ui\frontend; npm run build   # frontend typecheck + production build
```

The suite covers ingestion, prompt packages, response parsing, escalation,
checkpointing, metrics, normalization/discrepancy, the review API against the
contracts seam, the Postgres store against scripted fakes, and both scripts.

## Project status

| Area | Implementation state | Remaining acceptance |
|---|---|---|
| Ingestion (quality gate, 300 DPI conversion, raw S3 preservation) | Implemented; offline-tested | Re-run against the approved live bucket/credentials |
| Drawing/screenshot extraction (two-tier routing, tiling, hybrid batch, checkpoints) | Implemented; offline-tested | Run the approved source corpus with paid model access |
| Topics extraction (LLM-primary parser, deterministic validation, vision pass) | Implemented; offline-tested | Run against the approved topics export and model endpoint |
| Normalization, deduplication, discrepancy, source traceability | Derived Floor-02 artifacts rebuilt and offline-verified | Reviewer acceptance; naming convention decision |
| Relationships | 44 evidence-backed candidate edges preserved and review-routed | Engineer review and approval |
| Human review board and database handoff | Fake/Postgres paths implemented; offline-tested for local/internal use | Select and integrate authentication/authorization before any network-exposed deployment; then admin grant, live table setup, and a real review-session commit |
| Downloads sync, upload, metrics, runbooks | Implemented; offline-tested | Live S3/upload smoke and walkthrough-video recording |
| Per-floor deliverables | Floor 02 path and artifact set implemented | Folder convention decision plus source runs for other floors |
| Single-command end-to-end orchestration | Not implemented; stages have explicit contracts and commands | Optional post-project integration work |
| Point classification | Descoped by the supervisor's final direction | None for this project |
| Zone orientation | Placeholder view only; no separately accepted implementation | Confirm whether it was descoped with point classification |

No live AWS, paid-model, or production-database operation is performed by the
offline test suite. Review-table creation is additionally blocked on the
one-time admin grant documented in `docs/`; the walkthrough recording requires
an operator. These boundaries are acceptance items, not implied successes.

## Documentation

| Document | Contents |
|---|---|
| [`docs/pipeline_struggles_report.md`](docs/pipeline_struggles_report.md) | What went wrong, how it was solved, lessons learned |
| [`docs/review_walkthrough.md`](docs/review_walkthrough.md) | Reviewer guide, live-DB runbook, video script |
| [`docs/relationship_graphics_findings.md`](docs/relationship_graphics_findings.md) | The relationships method and its validation |
| [`docs/cost_estimate.md`](docs/cost_estimate.md) | Measured spend and per-site projections |
| [`docs/audit_closeout_2026-07-12.md`](docs/audit_closeout_2026-07-12.md) | Reconciled scope, offline evidence, and remaining authorization gates |
| [`docs/HISTORY.md`](docs/HISTORY.md) | Chronological W2–W7 build record (lab notebook) |
| [`docs/README.md`](docs/README.md) | Full documentation index |

---

*Project ORIENT Part I — built by Team 4, Summer 2026. The database this
pipeline produces is the foundation for Part II (FDD rules and analytics).*
