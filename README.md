# Project ORIENT — Ingestion and Equipment Extraction Foundation

Project ORIENT is an ingestion pipeline for S3-based Building Management System
(BMS) screenshots, control drawings, and mechanical drawing files. The current
implementation focuses on the data engineering foundation: discovering source
files, preserving raw inputs, preparing image/PDF inputs, validating image
quality, and keeping outputs reviewable before any production database writes.

## Current Functionality

- Reads `S3_BUCKET`, `S3_INPUT_PREFIX`, `S3_OUTPUT_PREFIX`, and
  `S3_RAW_PREFIX` from the project root `.env` file.
- Lists files from the configured S3 input prefix.
- Excludes `S3_OUTPUT_PREFIX` while listing inputs to prevent recursive
  reprocessing of generated pipeline outputs.
- Downloads source files to `tmp/orient/`.
- Detects file types:
  - `image` for `.png`, `.jpg`, `.jpeg`
  - `pdf` for `.pdf`
  - `dwg` for `.dwg`
  - `unsupported` for anything else
- Skips unsupported files without treating them as errors.
- Checks image quality using orientation-aware long-side and short-side
  thresholds in `pipeline/ingestion.py`.
- Converts PDFs to PNG page images at a minimum of 300 DPI.
- Uploads passed-quality images to `processed/`.
- Uploads failed-quality images to `review/failed_quality/`.
- Writes a local run manifest to `tmp/orient/manifest.json`.
- Uploads a timestamped manifest to `S3_OUTPUT_PREFIX/manifests/`.
- Plans raw-source uploads under configurable `S3_RAW_PREFIX` with dry-run,
  duplicate-key detection, no-overwrite behavior, and SHA-256 metadata.

Database writes and LLM calls are intentionally not implemented yet.

## AWS MFA Workflow

Temporary AWS MFA credentials must be set in your PowerShell session before
running the pipeline. Do not store AWS access keys or session tokens in `.env`.

The `.env` file should contain project configuration only, such as the bucket and
prefixes. Keep real AWS credentials in your temporary shell environment.

## Environment Setup

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

## Install Dependencies

```powershell
py -m pip install -r requirements.txt
```

`pdf2image` requires Poppler on Windows. If PDF conversion fails with a Poppler
message, install Poppler and add its `bin` folder to your `PATH`.

## Run

```powershell
py pipeline\run.py
```

## Expected Output

When the pipeline runs successfully, it should:

- Print the files found under `S3_INPUT_PREFIX`.
- Skip unsupported files cleanly.
- Download source files to `tmp/orient/`.
- Run image quality checks for image inputs.
- Convert PDF files into PNG page images.
- Upload passed-quality images under `S3_OUTPUT_PREFIX/processed/`.
- Upload failed-quality images under `S3_OUTPUT_PREFIX/review/failed_quality/`.
- Create `tmp/orient/manifest.json`.
- Upload a timestamped manifest under `S3_OUTPUT_PREFIX/manifests/`.

## Progress Completed

The project now supports:

- Recursive local discovery of `.png`, `.jpg`, `.jpeg`, `.pdf`, and `.dwg`
  files.
- File metadata capture, including relative paths, file size, and SHA-256
  checksums.
- Read-only source handling for local discovery and manifest creation.
- PDF-to-image conversion at a minimum of 300 DPI.
- Deterministic PDF page names and optional Poppler configuration.
- Orientation-aware image-quality validation using a minimum long side of 1000
  pixels and a minimum short side of 750 pixels.
- Oversized-image warnings for images over 100,000,000 pixels.
- Real smoke testing with `AHU_02A.png`, `VAVRH_2_1.png`, and `Floor_2A.pdf`.
- Configurable raw S3 prefix using `S3_RAW_PREFIX`.
- Dry-run raw upload planning with original relative-folder preservation.
- Duplicate-key detection and no-overwrite behavior by default.
- SHA-256 stored in S3 upload metadata for raw-source uploads.
- Mocked S3 tests with no live AWS dependency.
- A current full test suite of 79 passing tests.

Recent local checkpoints:

```text
5484e8d Add local source file manifest ingestion
ef573cb Harden 300 DPI PDF conversion
76fe23a Improve image quality validation
4ec28e2 Add raw source S3 upload workflow
```

## Current Status

Initial Floor 02 data exploration has been completed against the PostgreSQL
`topics` table and sample BMS screenshots/mechanical drawings.

Current findings and artifacts:

- Confirmed that `msa_orient_building_1` contains 595 Floor 02 topics.
- Identified 44 raw equipment groups across AHU, FCU, VAV, VAVRH, FPTU,
  OAVAV, and EAVAV naming patterns.
- Added `data/snapshots/w03/equipment_from_topics_raw.csv`, containing the raw
  equipment inventory inferred from topic names.
- Added `data/snapshots/w03/equipment_from_drawings_raw.csv`, currently seeded
  with manually verified examples from BMS graphics and a mechanical drawing.
- Confirmed that equipment extraction from topics and drawings must remain
  separate until normalization, deduplication, and discrepancy analysis.

Current boundaries:

- No production database writes have been made.
- No committed Week 3 snapshots were modified by the recent ingestion phases.
- No live S3 upload has yet been performed.
- No vision-model endpoint has yet been deployed or called.
- `pipeline/llm_client.py` remains a placeholder.
- The local computer is suitable as the pipeline client, but not as a Qwen3-VL
  inference host.

Likely inference architecture:

```text
ProjectOrient client
-> OpenAI-compatible API
-> remote Linux GPU host
-> Docker + vLLM
-> Qwen3-VL
```

## Likely Next Direction

1. Confirm Joulea's approved GPU or inference environment.
2. Determine whether a shared vLLM endpoint already exists.
3. Select the appropriate Qwen3-VL model size based on available GPU memory.
4. Deploy or connect to a remote vLLM endpoint.
5. Smoke-test text and single-image requests.
6. Implement the ProjectOrient OpenAI-compatible vision client.
7. Create the v1 few-shot equipment-extraction prompt.
8. Pilot extraction with `AHU_02A.png` and `VAVRH_2_1.png`.
9. Determine how to resize, crop, or tile very large mechanical drawings.
10. Run a limited Floor 02 development extraction before broader processing.

## Core Questions for the Joulea Team

1. Is a shared GPU server or vLLM endpoint already available?
2. If not, which cloud provider, account, and budget should the team use?
3. Is Qwen3-VL an approved model choice?
4. Is there a preferred Qwen3-VL model size or configuration?
5. Must the inference endpoint use Docker and vLLM?
6. Are building screenshots, PDFs, and DWGs permitted on an external cloud GPU?
7. What authentication and network-security requirements apply?
8. Does "batch mode" mean a provider-supported batch API or bounded concurrent
   requests?
9. Should `S3_RAW_PREFIX` be `Team-4/raw/`, or is another folder convention
   required?
10. Should Week 3 model output populate `equipment_details` directly, or remain
    staged for human review?
11. Should `canonical_name` be treated as a Week 3 model candidate or deferred
    entirely to Week 4 normalization?
12. How should `EAVAV` be classified?
13. Are `OAVAV`, `VAVRH`, and `FPTU` expected to remain explicit equipment
    types?
14. Are there required image-size, token, rate-limit, or batch constraints?
15. Who owns and maintains the inference endpoint after deployment?
