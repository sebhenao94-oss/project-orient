# Project ORIENT — Ingestion and Equipment Extraction Foundation

Project ORIENT is an ingestion pipeline for S3-based Building Management System
(BMS) screenshots, control drawings, and mechanical drawing files. The current
implementation focuses on the data engineering foundation: discovering source
files, preserving raw inputs, preparing image/PDF inputs, validating image
quality, and keeping outputs reviewable before any production database writes.

## Current Functionality

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
  thresholds in `pipeline/ingestion.py`.
- Preserves corrupt-image failures and oversized-image warnings in typed output.
- Produces `AIReadyImageRecord` records for PNG/JPG/JPEG images and converted
  PDF pages that Stage 2 can consume without redoing ingestion work.
- Keeps DWG files supported for manifest and raw-storage planning, but treats
  them as raw-only/deferred for image preparation.
- Keeps unsupported regular files in the source manifest as skipped.
- Keeps `pipeline/run.py` as a thin local CLI over the canonical Stage 1
  function. It defaults to dry-run raw-upload planning unless `--upload` is
  provided.

Database writes, LLM calls, DWG rendering, normalization, deduplication,
relationship mapping, point classification, and review UI behavior are
intentionally outside Stage 1.

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

Dry-run local Stage 1 preparation:

```powershell
py -m pipeline.run "C:\path\to\source_files" --raw-prefix Team-4/raw/
```

To perform real raw-source S3 uploads, add `--upload`. By default, the command
plans raw uploads only and does not require live AWS credentials. Module invocation is
the canonical CLI form; direct script help with `py pipeline\run.py --help` remains
supported for compatibility.

## Expected Output

When the Stage 1 CLI runs successfully, it should:

- Report the number of source-manifest records discovered.
- Report raw-upload results as `planned`, `uploaded`, `conflict`, or `skipped`.
- Convert PDF files into deterministic PNG page images under the local work
  directory.
- Produce prepared-image records for valid image inputs and converted PDF pages.
- Preserve image dimensions, pixel counts, quality status, quality reasons, and
  warnings.
- Mark insufficient or corrupt images as not eligible for automatic extraction.
- Mark DWG sources as deferred raw-only inputs without attempting conversion.

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
- A current full test suite covering ingestion, prompt loading, response parsing, models, and snapshot validation.

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
- A controlled live raw-source S3 upload has been completed and verified.
- No persistent production vision-model endpoint has yet been deployed or called.
- `pipeline/llm_client.py` remains a placeholder.
- The local computer is suitable as the pipeline client, but not as a Qwen3-VL
  inference host.

Temporary inference smoke-test status:

- A temporary Google Colab smoke test succeeded on a Tesla T4 runtime.
- `Qwen/Qwen3-VL-2B-Instruct` was loaded for development validation.
- Direct text inference and direct vision inference both succeeded.
- A temporary OpenAI-style FastAPI endpoint was tested inside Colab.
- Correct credentials returned `200`; incorrect credentials returned `401`.
- A minimal chat completion returned `ORIENT_ENDPOINT_OK`.
- Five requests succeeded and the sixth returned `429` under the temporary
  configured rate limit.
- The smoke-test endpoint used Hugging Face Transformers plus FastAPI, not a
  completed vLLM deployment.
- The endpoint was localhost-only inside Colab, so this Windows repository
  cannot currently reach it.
- No credentials, active Colab URLs, or secrets are committed.

Likely inference architecture:

```text
ProjectOrient client
-> OpenAI-compatible HTTP endpoint
-> GPU inference host
-> open-weights vision-language model
```

## Likely Next Direction

1. Confirm Joulea's approved GPU or inference environment.
2. Determine whether a shared vLLM endpoint already exists.
3. Select the appropriate Qwen3-VL model size based on available GPU memory.
4. Deploy or connect to a persistent remote inference endpoint.
5. Smoke-test text and single-image requests against that persistent endpoint.
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
