# Project ORIENT

Project ORIENT turns messy Building Management System (BMS) screenshots and
mechanical drawings into a clean, human-verified HVAC equipment / relationship /
point database for downstream Fault Detection & Diagnostics. The pipeline runs in
five stages — ingestion, equipment extraction, relationship mapping, point
tagging, and a mandatory human review step — and **nothing reaches the production
database except through the review agent.**

## Core questions

Open items we still need answers on from the supervisors. They shape the
canonical equipment list and the W7 point-classification work:

1. **How should `EAVAV` units be classified?** They show up in the Floor 02
   topics (5 contexts) but are not in the equipment quick reference.
2. **Do `OAVAV`, `VAVRH`, and `FPTU` stay as their own equipment types**, or
   should they be folded into the standard quick-reference types (`VAV`,
   `VAV-RH-HW`, `FPTU-HW`, ...)?

## Build status by week

| Stage / week | Area | State |
|---|---|---|
| Stage 1 (W2) | Ingestion (PNG/JPG/PDF → 300 DPI, quality check, S3 raw) | Done — see "Stage 1 ingestion" below |
| Stage 2 (W3) | Equipment extraction (vision LLM + strict parsing) | Done — history in `docs/HISTORY.md` |
| Stage 2 (W4) | Normalization, discrepancy/gap report, relationship mapping | Done — see `data/snapshots/w04/README.md` |
| **Review agent (W5)** | **Review backend: API + store + atomic commit path** | **Done (offline) — see "W5 — Review Agent Backend" below** |
| **Review agent (W6)** | **Review frontend (React + react-flow, 4 views) + W4-review follow-ups** | **Done — see "W6 — Review Agent Frontend & W4-Review Follow-ups" below** |

> **Inference note:** the pipeline now runs on the **Anthropic Claude API** (cheapest-first
> escalation: free Qwen L1 → Haiku → Sonnet → Opus + drawing tiling) behind the
> OpenAI-compatible `llm_client` seam — *not* the Qwen/Colab endpoint described in the
> historical W3 record.

> The chronological W2–W3 build record (pilots, live validation results, failure
> modes, and the original supervisor question list) lives in
> [`docs/HISTORY.md`](docs/HISTORY.md). This README describes the current state
> and how to run everything.

## Current state (through W6)

The full pipeline now runs end-to-end and its outputs flow into a working human review
agent (backend **and** frontend). Nothing reaches the production DB except through an
explicit review-session commit.

- **Inference:** Anthropic Claude via the escalation ladder (`pipeline/escalation.py`,
  `anthropic_client.py`, `tiling.py`, `cost.py`); ~$0.35 spent to date, `$20/mo` cap —
  see [`docs/cost_estimate.md`](docs/cost_estimate.md).
- **Topics → equipment (LLM-assisted, primary):** `pipeline/topics_parser.py` groups BMS
  topic names with an LLM (no fixed `<floor>/<eq>/<point>` assumption) and keeps the old
  deterministic path-parse only as a validation cross-check. Flagged units get a **vision
  second pass** before human review.
  ```powershell
  py -m pipeline.topics_parser --topics-csv <csv> --output-path outputs\Floor_2\topics_equipment_floor_02.csv `
    --property-id b470b97b-4ea7-481c-97b7-22a81a219587 --property-name msa_orient_building_1 `
    --floor-prefix Floor_02 --run-live --vision-escalate-dir downloads\Floor_2 --example-image-dir downloads\Floor_2
  ```
- **Drawings → equipment / relationships:** equipment extraction with the current-best
  `equipment_extraction_v4` prompt; relationships via **full-resolution tiling** on the
  mechanical drawings (`pipeline/relationship_tiling.py` — the W4 "0 edges" unblock).
- **Naming convention:** a single `canonical_name` in `{Type}_{floor}-{unit}` zero-padded
  form (`AHU_2-01`, `VAV-RH-HW_2-01`), matching the DB Floor-1 worked example.
- **Inputs / outputs:** source files live in `downloads/<floor>/` (populate with
  `python scripts/populate_downloads.py --floor Floor_2`); pipeline outputs go to
  `outputs/<floor>/`.
- **Review agent:** FastAPI backend (`review_api/app.py`) + React frontend
  (`review_ui/frontend/`). See the **W5** and **W6** sections below to run each.

## Setup

### Environment

Copy the example environment file into the project root:

```powershell
Copy-Item config\.env.example .env
```

Set these S3 values in `.env`:

```text
S3_BUCKET=msa-summer-2026
S3_INPUT_PREFIX=Team-4/
S3_OUTPUT_PREFIX=Team-4/pipeline_outputs/
S3_RAW_PREFIX=Team-4/raw/
```

`config/.env.example` documents every variable (S3, DB, ingestion thresholds,
LLM provider/model/limits). Never commit a real `.env` or any credential.

### AWS MFA workflow

Temporary AWS MFA credentials must be set in your PowerShell session before
running the pipeline. Do not store AWS access keys or session tokens in `.env`.

The `.env` file should contain project configuration only, such as the bucket and
prefixes. Keep real AWS credentials in your temporary shell environment.

### Install dependencies

```powershell
py -m pip install -r requirements.txt
```

`pdf2image` requires Poppler on Windows. If PDF conversion fails with a Poppler
message, install Poppler and add its `bin` folder to your `PATH`.

## Run

### Stage 1 — ingestion (dry-run by default)

```powershell
py -m pipeline.run "C:\path\to\source_files" --raw-prefix Team-4/raw/
```

To perform real raw-source S3 uploads, add `--upload`. By default, the command
plans raw uploads only and does not require live AWS credentials. Module invocation is
the canonical CLI form; direct script help with `py pipeline\run.py --help` remains
supported for compatibility.

When it runs successfully it reports the source-manifest records discovered,
raw-upload results (`planned` / `uploaded` / `conflict` / `skipped`), converts
PDFs to deterministic 300 DPI PNG pages, and marks insufficient or corrupt
images as not eligible for automatic extraction.

### Stage 2 — equipment extraction

```powershell
py -m pipeline.extraction extract `
  --input-dir "C:\path\to\prepared\floor02\images" `
  --prompt-root ".\prompts\equipment_extraction" `
  --example-image-dir "C:\path\to\few_shot_images" `
  --property-id "b470b97b-4ea7-481c-97b7-22a81a219587" `
  --property-name "msa_orient_building_1" `
  --prompt-version equipment_extraction_v4 `
  --snapshot-version w03 `
  --floor Floor_02 `
  --output-dir data\extractions\w03 `
  --raw-runs-path data\extractions\w03\equipment_extraction_runs.jsonl `
  --snapshot-path data\snapshots\w03\drawing_equipment_floor_02.csv `
  --model $env:LLM_MODEL `
  --max-concurrency 1 `
  --run-live
```

Topics → equipment uses the LLM-assisted parser command shown in "Current
state" above. The W4 normalization / discrepancy / graph-validation stages run
offline from the committed snapshots:

```powershell
py -m pipeline.normalization --overwrite
py -m pipeline.discrepancy
py -m pipeline.graph_validator
```

### Review agent (backend + frontend)

```powershell
# 1. backend (fake store, no DB/creds)
$env:REVIEW_STORE = "fake"; py -m uvicorn review_api.app:app --reload   # http://127.0.0.1:8000/docs
# 2. frontend
cd review_ui\frontend; npm install; npm run dev                          # http://localhost:5173
#    live backend instead of mocks: set VITE_USE_MOCKS=false in review_ui\frontend\.env.local
```

### Tests

The full offline suite (no network / AWS / DB) must stay green:

```powershell
py -m unittest discover tests        # full offline suite
cd review_ui\frontend; npm run build # frontend typecheck + build
```

## Stage 1 ingestion — current functionality

- Reads S3 project settings such as `S3_BUCKET`, `S3_INPUT_PREFIX`,
  `S3_OUTPUT_PREFIX`, and `S3_RAW_PREFIX` from the project root `.env` file.
- Provides the canonical Stage 1 entry point
  `prepare_sources_for_extraction()` in `pipeline/ingestion.py`.
- Recursively discovers local `.png`, `.jpg`, `.jpeg`, `.pdf`, and `.dwg`
  sources and builds typed source-manifest records.
- Captures source metadata, relative paths, file size, and SHA-256 checksums.
- Plans or uploads original raw source files under configurable `S3_RAW_PREFIX`
  with dry-run support, duplicate-key detection, no-overwrite behavior, and
  SHA-256 S3 object metadata.
- Converts PDFs to deterministic PNG page images at a minimum of 300 DPI.
- Checks source images and converted PDF pages using orientation-aware quality
  thresholds in `pipeline/ingestion.py` (environment-configurable:
  `INGESTION_MIN_IMAGE_LONG_SIDE`, `INGESTION_MIN_IMAGE_SHORT_SIDE`,
  `INGESTION_MAX_RECOMMENDED_PIXEL_COUNT`).
- Preserves corrupt-image failures and oversized-image warnings in typed output.
- Produces `AIReadyImageRecord` records for PNG/JPG/JPEG images and converted
  PDF pages that Stage 2 can consume without redoing ingestion work.
- Keeps DWG files supported for manifest and raw-storage planning, but treats
  them as raw-only/deferred for image preparation.
- Keeps unsupported regular files in the source manifest as skipped.

Database writes, LLM calls, DWG rendering, normalization, deduplication,
relationship mapping, point classification, and review UI behavior are
intentionally outside Stage 1.

## W5 — Review Agent Backend

Week 5 builds the **backend and data wiring for the human review agent** — the
mandatory approval layer between the pipeline's extracted outputs and the
production database. Pipeline stages emit versioned files only; an engineer
reviews equipment, relationships, and discrepancies, and **only an explicit
session commit writes approved data to the production tables** (rejections go to a
correction log that feeds the few-shot loop).

### Architecture — one interface, two stores

The backend is split along a single typed seam, `review_api/contracts.py`, which
defines the `ReviewStore` Protocol plus the request/response DTOs and query
objects. Two implementations satisfy it interchangeably:

```text
FastAPI app (review_api/app.py)
  -> ReviewStore (review_api/contracts.py)   # the frozen interface
       -> FakeReviewStore  (review_api/fake_store.py)  # in-memory, seeded from data/snapshots/w04/*
       -> PostgresReviewStore (pipeline/review_store.py) # live DB; atomic commit transaction
```

The app is written once against the interface and selects the store at runtime
via the `REVIEW_STORE` env var (`fake` by default, `postgres` for the live
cutover). The fake store needs no credentials and is seeded from the committed W4
snapshots, so the entire API and its tests run fully offline.

### Endpoints

Read (server-side sort/filter/group; the W6 frontend stays thin):

```text
GET  /equipment        list/sort/filter; default sort = confidence ascending (riskiest first)
GET  /relationships    edges + orphans + validator errors (renders the current empty set: 0 edges / 50 orphans)
GET  /discrepancies    the gap report; group_by = floor | equipment_type | severity_hint; + rollup headlines
GET  /zones            empty until W7
```

Session / write (the transaction lives in the store, not the HTTP layer):

```text
POST /sessions                 open a review sitting
GET  /sessions/{id}            session state (pending / approved / rejected counts)
POST /sessions/{id}/actions    record an approve / edit / reject decision
POST /sessions/{id}/commit     atomically commit: approved -> production, rejected -> correction_log
```

OpenAPI docs render at `/docs`; ReDoc at `/redoc`.

The fake store reproduces the committed W4 Floor-02 data faithfully: 56 equipment
units (11 settled), discrepancies 11 matched / 19 missing_from_drawings (4 high =
AHUs) / 19 missing_from_points / 7 resolved_out_of_scope (the Floor-1 trap units),
0 relationship edges with 50 orphans (`passed=true`), and an empty zone list.

### Deferred (DB cutover — not required for the W5 "runs locally" deliverable)

- **Review tables in the live database.** `review_session`, `review_action`, and
  `correction_log` must be created in `bas_data` by a DB admin (see
  `docs/w5_database_admin_request.md`), which also grants the team `INSERT/UPDATE`
  on them. No application code can do this; it is an ops step at the W6→W7 deploy
  boundary.
- **Write-path verified against a real database.** The atomic `commit_session`
  transaction is correct by construction and tested against scripted fakes, but
  has not yet been exercised against a live SQL engine. This is closed by running
  the `PostgresReviewStore` against a disposable local Postgres or the live DB once
  the tables above exist.

Writing real, unreviewed W4 output to the production `equipment_details` table is
**intentionally not done**: that table feeds FDD, the W4 data is mostly flagged for
review, and no engineer has approved a real session yet.

## W6 — Review Agent Frontend & W4-Review Follow-ups

Week 6 adds the **React review frontend** over the W5 backend and closes the supervisor's
W4-code-review feedback.

### Review frontend (`review_ui/frontend/`)

React + TypeScript (Vite) + `@xyflow/react`. Four views over the W5 API:

1. **Equipment** — approve / edit / reject; sorted so flagged/low-confidence items surface
   first (falls back to `review_required` when confidence is absent — real data is unscored).
2. **Relationships** — interactive react-flow graph; drag a terminal onto its AHU to
   propose an `airRef`; edges approve/edit/reject.
3. **Discrepancies** — the W4 gap report grouped by severity / floor / equipment type with
   rollup headlines.
4. **Zones** — confirm/correct orientation (data lands in W7).

Session progress bar + **flush-and-continue commit** (a committed batch locks; undecided
items stay actionable). The UI is **decoupled from the moving contract** via a single
`src/api/adapter.ts` seam and runs on mock data by default.

The backend sends CORS headers for the Vite dev origin, and
`PostgresReviewStore.commit_session` allows **partial (batch) commits** to match the UI.

### W4-code-review follow-ups (Sourav)

| Item | What changed |
|---|---|
| Dedupe canonical columns | Dropped `canonical_key` from the public surface; single `canonical_name` in zero-padded `{Type}_{floor}-{unit}` form (`AHU_2-01`). `canonical_key` survives internally as the dedup key only. |
| Source-file traceability | Extraction output carries `source_filename` / `source_relative_path` / `source_sha256`. |
| Equipment→equipment relationships (`airRef`) | Built tiled Opus extraction (`relationship_tiling.py`). Floor plans proved a *weak* serving source (candidate edges → review); recommend schedules/risers/BMS nav-tree next. |
| Per-floor outputs | `outputs/<floor>/`. |
| Standardize inputs | `downloads/<floor>/` + `scripts/populate_downloads.py`. |
| No `v1/v2/v3` prompt files | Collapsed to single current-best (`equipment_extraction_v4`, `relationship_mapping_v2`); iterate in place, git tracks history. |
| LLM-assisted topic parsing (not deterministic) | `pipeline/topics_parser.py` is the primary path; deterministic parse kept as validation. |
| Vision escalation for flagged items | Flagged units route their screenshot to a vision second pass before human review. |
| Tier vision by complexity | `escalation.py` ladder: drawings → top tier, simple screenshots → cheaper. |

## Cost

Inference runs on per-team Claude API keys with a **$20/month** cap. Spend to
date is roughly **$0.35**. Per-run token usage and estimated cost are logged by
`pipeline/cost.py` (`write_cost_log`) for the W8 performance analysis. Projected
per-floor and per-site costs, with the assumptions behind them, are in
[`docs/cost_estimate.md`](docs/cost_estimate.md).

## History

The chronological W2–W3 build record — Stage 1 progress, the Colab/Qwen
smoke tests, live validation results, pilot failure modes, and the original
supervisor question list — is preserved verbatim in
[`docs/HISTORY.md`](docs/HISTORY.md).
