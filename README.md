# Project ORIENT — Ingestion and Equipment Extraction Foundation

## Purpose

Project ORIENT automates the extraction and classification of HVAC equipment
from Building Management System (BMS) data for Joulea's building analytics
platform. The goal is to take raw BMS screenshots, control drawings, mechanical
drawing files, and PostgreSQL topic tables and produce a clean, validated
equipment inventory that can be written to the production database.

The pipeline covers three stages:

1. **Ingestion** — discover, validate, and archive source image and PDF files
   from S3; convert PDFs to images; flag quality issues before any extraction
   work begins.
2. **Extraction** — use a vision-language model (Qwen3-VL via an
   OpenAI-compatible endpoint) to read equipment identifiers from BMS
   screenshots and drawings; separately export equipment contexts from the
   PostgreSQL `topics` table.
3. **Normalization and review** — deduplicate and reconcile equipment found
   across drawings and topics; map raw labels to canonical equipment types
   (defined in `equipments_point_types/`); flag discrepancies for human review
   before any production database writes.

## Repository Structure

```
project-orient/
├── pipeline/                   Core pipeline modules
│   ├── ingestion.py            Stage 1: source discovery, image quality, S3 upload
│   ├── extraction.py           Stage 2: equipment extraction CLI (drawings + topics)
│   ├── normalization.py        W4: canonical name and type normalization
│   ├── discrepancy.py          W4: cross-source discrepancy detection
│   ├── relationships.py        W4: equipment relationship mapping
│   ├── equipment_prompts.py    Prompt loading for equipment extraction
│   ├── relationship_prompts.py Prompt loading for relationship mapping
│   ├── equipment_vocab.py      Equipment type vocabulary and BMS-to-library mapping
│   ├── llm_client.py           OpenAI-compatible vision client
│   ├── models.py               Pydantic data models for all pipeline records
│   ├── run.py                  Stage 1 CLI entry point
│   └── ...
│
├── equipments_point_types/     Equipment type definitions (source of truth)
│   ├── equip_air_handling.py   AHU, DOAS, MAU, FCU
│   ├── equip_air_terminal.py   VAV, VAVRH, FPTU, OAVAV, EAVAV variants
│   ├── equip_chw_plant.py      Chiller, CHW pump
│   ├── equip_cond_plant.py     Cooling tower, condenser pump
│   ├── equip_hw_plant.py       Boiler, HW pump
│   └── equip_ventilation.py    ERV
│
├── prompts/                    Versioned LLM prompt files
│   ├── equipment_extraction/   System prompt, user template, few-shot examples
│   └── relationship_mapping/   System prompt, user template, few-shot examples
│
├── data/
│   └── snapshots/              Committed pipeline output artifacts (CSV/JSON)
│       ├── w03/                Week 3: raw extraction and topics snapshots
│       └── w04/                Week 4: normalized, canonical, relationship outputs
│
├── downloads/                  Local S3 source files (git-ignored)
├── tests/                      Unit and integration tests
├── docs/                       Supporting documentation and pilot notes
├── review_api/                 FastAPI review interface (in progress)
├── config/
│   └── .env.example            Environment variable template
└── requirements.txt            Python dependencies
```

---

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
- Adds initial source-document routing on each prepared image:
  `bms_screenshot`, `mechanical_drawing`, or `unknown`. The route is based on
  path/name hints first (`screenshots`, `drawings`, `mechanical`, etc.) and
  large-image/PDF fallback signals.
- Adds `image_complexity` on each prepared image as `simple`, `moderate`,
  `complex`, or `unknown` from image dimensions and pixel count. This keeps
  source type from being the only escalation signal: a simple mechanical drawing
  can proceed after a good extraction, while a complex BMS screenshot can still
  be routed for review or stronger processing.
- Stage 2 carries that source-document routing into each extraction result and
  applies `pipeline/escalation.py` when writing the drawing snapshot. The
  escalation layer combines source type, image complexity, confidence, equipment
  type, and empty successful outputs. It flags low-confidence rows,
  `unknown class` equipment types, complex images, complex mechanical drawings
  that need a drawing second pass, unknown source types, and successful runs
  that found no equipment. Snapshot rows include
  `review_required`, `review_reason`, and `escalation_action` so review queues
  can explain why a row was accepted, retried, sent to source-type review, or
  sent to the mechanical-drawing second pass.
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

## Download Source Files from S3

The pipeline works against local files — source images and PDFs are not committed
to this repository. Download them from S3 into the `downloads/` folder before
running the pipeline. The `downloads/` folder is already git-ignored.

```bash
aws s3 sync s3://msa-summer-2026/Team-4/ ./downloads/ \
  --exclude "pipeline_outputs/*" \
  --exclude "raw/*"
```

The `--exclude` flags skip subfolders that contain pipeline-generated output, so
only original source files are downloaded.

If you are on Windows:

```powershell
aws s3 sync s3://msa-summer-2026/Team-4/ .\downloads\ `
  --exclude "pipeline_outputs/*" `
  --exclude "raw/*"
```

AWS credentials must be set in your shell before running this command. Use the
**Access keys** link in the AWS SSO portal to get temporary credentials.

> **Note for students:** Always download into the `downloads/` folder inside the
> repo rather than an arbitrary location on your machine. This keeps the path
> consistent with the run commands below and ensures the folder is git-ignored so
> no large binary files are accidentally committed.

## Install Dependencies

```powershell
py -m pip install -r requirements.txt
```

`pdf2image` requires Poppler on Windows. If PDF conversion fails with a Poppler
message, install Poppler and add its `bin` folder to your `PATH`.

## Run

Dry-run local Stage 1 preparation (after downloading source files into `downloads/`):

```bash
python -m pipeline.run "./downloads" --raw-prefix Team-4/raw/
```

On Windows:

```powershell
py -m pipeline.run ".\downloads" --raw-prefix Team-4/raw/
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
## W3 Equipment Extraction Vertical Slice

The Week 3 extraction path now separates each boundary explicitly:

```text
AIReadyImageRecord
-> EquipmentPromptPackage
-> EquipmentMessagePlan
-> OpenAI-compatible multimodal request
-> raw assistant content
-> strict EquipmentExtractionResponse parsing
-> EquipmentExtractionRunResult
-> JSONL run artifact and drawing-derived CSV snapshot
```

The OpenAI-compatible client uses `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`,
`LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, and `LLM_MAX_CONCURRENCY`. API keys
must remain in local environment configuration and are never logged or written to
artifacts.

Local image inputs are encoded as OpenAI-style data URLs:

```text
data:<mime-type>;base64,<encoded-bytes>
```

Supported request image MIME types are PNG, JPEG, and WebP. Stage 2 keeps raw
assistant text and strict parsing separate so malformed or schema-invalid model
output remains reviewable.

Run offline tests:

```powershell
py -m unittest tests.test_llm_client tests.test_w3_extraction
py -m unittest discover tests
```

One-image pilot command shape, after endpoint configuration and local few-shot
images are available:

```powershell
py -m pipeline.extraction extract `
  --input-dir "C:\path\to\prepared\floor02\images" `
  --prompt-root ".\prompts\equipment_extraction" `
  --example-image-dir "C:\path\to\few_shot_images" `
  --property-id "b470b97b-4ea7-481c-97b7-22a81a219587" `
  --property-name "msa_orient_building_1" `
  --prompt-version equipment_extraction_v2 `
  --snapshot-version w03 `
  --floor Floor_02 `
  --output-dir data\extractions\w03 `
  --raw-runs-path data\extractions\w03\equipment_extraction_runs.jsonl `
  --snapshot-path data\snapshots\w03\drawing_equipment_floor_02.csv `
  --model $env:LLM_MODEL `
  --max-concurrency 1 `
  --run-live
```

Single-image vision-model smoke test:

```bash
python -m pipeline.test_vision_model_output \
  --image "downloads/screenshots/YOUR_TARGET_IMAGE.png" \
  --example-image-dir "downloads/screenshots" \
  --source-document-type bms_screenshot \
  --image-complexity simple \
  --output-json "data/extractions/vision_test_result.json"
```

This command runs the model from `--model` when provided; otherwise it uses
`LLM_MODEL` from `.env`. It prints the raw assistant response, the parsed
`EquipmentExtractionResponse`, and an escalation preview. With
`--source-document-type bms_screenshot --image-complexity simple`, escalation is
not automatic: rows are accepted unless confidence is low, the equipment type is
`unknown class`, parsing/validation fails, or the successful run returns no
equipment. The escalation preview also prints the model that would be used for
the next action.

Escalation model routing uses these environment variables, falling back to
`LLM_MODEL` when an action-specific value is not configured:

| Escalation action | Model environment variable |
| --- | --- |
| `accept` | `LLM_MODEL` |
| `retry_screenshot_extraction` | `LLM_RETRY_MODEL` |
| `complex_image_review` | `LLM_COMPLEX_IMAGE_MODEL` |
| `mechanical_drawing_second_pass` | `LLM_MECHANICAL_DRAWING_MODEL` |
| `source_type_review` | `LLM_SOURCE_TYPE_REVIEW_MODEL` |
| `human_review` | `LLM_HUMAN_REVIEW_MODEL` |

Batch extraction uses independent bounded-concurrency Chat Completions requests.
It is not a provider-native discounted batch API, and throughput/cost must be
measured empirically for the deployed endpoint.

The raw run artifact writer stores complete provenance-rich results, including
transport and parsing failures. The drawing-derived CSV writer emits one row per
successful equipment candidate only. Model-proposed `canonical_name` values are
stored as provisional `llm_proposed_canonical_name` values and are not W4-approved
canonical names.


Topics-derived snapshot export command, after read-only DB environment variables and a
PostgreSQL Python driver are available:

```powershell
py -m pipeline.extraction topics `
  --property-name "msa_orient_building_1" `
  --floor-prefix Floor_02 `
  --output-path data\snapshots\w03\topics_equipment_floor_02.csv `
  --snapshot-version w03 `
  --expected-distinct-contexts 37
```
The topics-derived Floor 02 exporter is read-only. It groups topic paths by the
second path segment in `Floor_02/<equipment_context>/<point_name>`, strips only a
leading `DEV<digits>_` prefix for the raw label, and classifies raw types using
precedence: VAVRH, EAVAV, OAVAV, FPTU, FCU, AHU, VAV, UNRESOLVED. It does not
merge, normalize, deduplicate, or compare against drawing-derived rows. If
`--property-id` is omitted, the exporter resolves it from `public.property` by
`--property-name`.

Raw property topic-name CSV export command:

```powershell
py -m pipeline.extraction topic-names `
  --property-name "msa_orient_building_1" `
  --output-dir data\topic_names `
  --output-filename msa_orient_building_1_topic_names.csv
```

The `topic-names` exporter is also read-only. It downloads every
`public.topics.topic_name` for the property into `data/topic_names/` with
columns `property_id`, `property_name`, and `topic_name`. If `--property-id` is
omitted, the exporter resolves it from `public.property` by `--property-name`.

Current W3 topics-export target parameters:

```text
Role: orient_team_4
Property: msa_orient_building_1
Property ID: b470b97b-4ea7-481c-97b7-22a81a219587
Floor prefix: Floor_02
Expected topic rows: 456
Expected distinct contexts: 37
```

`public.tag` is treated as read-only. No database writes are part of W3. The live
database audit found a blocker for future equipment writes: `orient_team_4` lacks
USAGE on `public.equipment_details_equipment_id_seq`. An administrator must run:

```sql
GRANT USAGE
ON SEQUENCE public.equipment_details_equipment_id_seq
TO orient_team_4;
```

Do not manually allocate equipment IDs, write into `equipment_details`, update
`topics.equipment_id`, or modify the global tag vocabulary as part of W3.

## W3 Live Validation Results — June 10, 2026

### Verified workflow

The Week 3 equipment-extraction vertical slice has been exercised against live
infrastructure rather than offline mocks only.

The following path was verified:

```text
Floor 02 topics in PostgreSQL
-> read-only topics-derived equipment snapshot

Local prepared image
-> equipment_extraction_v2 prompt package
-> OpenAI-compatible multimodal request
-> Qwen3-VL inference
-> strict response parsing
-> provenance JSONL
-> drawing-derived equipment snapshot CSV
```

### Topics-derived Floor 02 snapshot

The read-only topics exporter connected to `bas_data` through the SSH tunnel and
generated:

```text
data/snapshots/w03/topics_equipment_floor_02.csv
```

Validated source parameters:

```text
Role: orient_team_4
Property: msa_orient_building_1
Property ID: b470b97b-4ea7-481c-97b7-22a81a219587
Floor: Floor_02
Source topic rows: 456
Distinct equipment contexts: 37
```

Observed raw-type distribution:

| Raw type | Contexts |
| -------- | -------: |
| AHU      |        6 |
| EAVAV    |        5 |
| FCU      |        1 |
| FPTU     |        1 |
| OAVAV    |       15 |
| VAV      |        4 |
| VAVRH    |        5 |

Three contexts contain only one topic row and are marked for review because
their topic evidence is weak:

```text
DEV205009_VAV_02_02
DEV205012_VAV_02_05
DEV205015_AHU-02A
```

This snapshot is raw W3 evidence only. It does not perform W4 normalization,
cross-source matching, deduplication, discrepancy analysis, or relationship
mapping.

### Open-weights model and endpoint smoke test

The development inference environment used:

```text
Model: Qwen/Qwen3-VL-2B-Instruct
Runtime: Google Colab
GPU: NVIDIA Tesla T4
GPU memory: approximately 14.6 GB
Model dtype: float16
```

A direct model-generation smoke test returned:

```text
ORIENT_MODEL_OK
```

A temporary OpenAI-compatible FastAPI wrapper was then tested successfully:

```text
GET  /v1/models             -> HTTP 200
POST /v1/chat/completions   -> HTTP 200
Model response              -> ORIENT_ENDPOINT_OK
```

The Windows repository client successfully authenticated to and invoked this
endpoint through a temporary development tunnel. Temporary endpoint URLs and API
keys are not stored in the repository.

The Colab and quick-tunnel setup is development-only and ephemeral. It is not a
production hosting design.

### One-image live multimodal pilot

The complete repository-integrated extraction path was run against
`AHU_02A.png`.

Generated artifacts:

```text
data/extractions/w03/pilot_ahu_02a_runs.jsonl
data/snapshots/w03/pilot_drawing_equipment_ahu_02a.csv
```

Final validated extraction:

```json
{
  "equipment": [
    {
      "raw_label": "AHU 02 A",
      "canonical_name": "AHU_02A",
      "equipment_type": "AHU",
      "confidence": 0.98
    }
  ]
}
```

The final run status was `succeeded`, strict JSON parsing passed, and the drawing
snapshot contains one equipment row.

### Failure modes found during the pilot

The live test exposed three useful failure modes.

1. **GPU memory pressure**

   Sending all five full-resolution few-shot images plus the target image in one
   request exceeded the Tesla T4 memory limit. The temporary endpoint mitigated
   this by resizing each image to a maximum side length of 768 pixels before
   inference.

   A production inference service should make image resolution, visual-token
   limits, concurrency, and GPU-memory policy explicit rather than relying on an
   ad hoc endpoint patch.

2. **Point labels incorrectly emitted as equipment**

   An early response emitted labels such as `DA Fan Sp`, `DA Fan Cnd`,
   `DA Temp`, and `DA Flow` as equipment candidates. These are point-level
   measurements, commands, or statuses rather than physical equipment.

   The v2 prompt was hardened with a mechanical candidate gate requiring a
   concrete equipment identifier beginning with one of:

   ```text
   AHU, VAVRH, VAV, FPTU, OAVAV, FCU
   ```

3. **Few-shot label leakage**

   An early successful response copied `VAVRH_2_1` from a demonstration image
   into the target-image result.

   The prompt now states that few-shot images are demonstrations only and that
   every returned identifier must have direct visual evidence in the final target
   image.

The strict parser correctly preserved and rejected malformed or truncated model
responses rather than silently repairing them.

### Interpretation of the pilot result

This pilot proves that the complete technical integration works:

```text
repository
-> prompt construction
-> image serialization
-> authenticated remote endpoint
-> open-weights vision inference
-> schema validation
-> provenance artifact
-> snapshot artifact
```

However, `AHU_02A.png` is also one of the few-shot demonstration images.
Therefore, the result is an integration smoke test, not an independent extraction
accuracy measurement.

An independent target image that is not present in the few-shot set should be
tested before making accuracy claims.

## W3 Floor 02 Batch Results — June 11, 2026

### Independent pilot

The first extraction against an image not present in the few-shot set
(`ahu_02c.png`) was run live. The v2 prompt returned two few-shot example
labels that are not visible in the target image and only 3 of roughly 24
visible identifiers. This motivated `equipment_extraction_v3` (see
`prompts/equipment_extraction/README.md`) and a client `max_tokens` fix:
dense pages exceeded the endpoint's 512-token completion default, so the
client now sends `LLM_MAX_COMPLETION_TOKENS` (default 2048) on each request.

With v3, the same pilot returned 21 correct identifiers with zero few-shot
leakage and zero hallucinations at a 768-pixel endpoint image cap, and 18
identifiers including the page header at a 900-pixel cap. Resolution changed
which small navigation-tree labels were captured; both runs are committed as
snapshots (`pilot_independent_equipment_v3_768.csv`,
`pilot_independent_equipment_v3_900.csv`) alongside the failed v2 run
(`pilot_independent_equipment.csv`) as evidence.

### Floor 02 batch

The complete available Floor 02 BMS screenshot set (22 images, including the
few-shot example pages, which are flagged as contaminated evidence) was run
at a 900-pixel endpoint cap with `equipment_extraction_v3`:

```text
20 succeeded, 1 skipped (resolution), 1 validation_failed (out-of-scope type)
53 raw rows, 31 distinct labels across AHU, FCU, FPTU, OAVAV, VAV, VAVRH
Batch wall time: 216 seconds at concurrency 1
data/snapshots/w03/drawing_equipment_floor_02.csv
```

The ingestion image-quality thresholds are now environment-configurable
(`INGESTION_MIN_IMAGE_LONG_SIDE`, `INGESTION_MIN_IMAGE_SHORT_SIDE`,
`INGESTION_MAX_RECOMMENDED_PIXEL_COUNT`) with unchanged defaults. The batch
ran with the short side lowered to 700 because 11 of the 22 real BMS
screenshots are 715-747 pixels tall and were skipped at the 750 default.

Known defects preserved in the raw snapshot for W4 review (rows are
deliberately not cleaned):

* `VAVRH_2_1` (a remaining few-shot label) leaked onto roughly 5 pages where
  it is not visible.
* Two FCU page headers were misread (`fcu_02_1.png` returned `FCU_02_3`;
  `fcu_02_4.png` returned `FCU_02_1`).
* `OAVAV_2_09.png` was misread as `DAWNV_2_09`.
* `OAVAV_02_01.png` returned a real but out-of-scope `DOAS` label, which
  strict schema validation correctly rejected (`validation_failed`).
* One within-image duplicate (`FCU_02_5`) was not suppressed.
* Model confidence is uniformly 0.99 and is not calibrated; no row
  self-reported below the 0.75 review threshold.

### Drawing probe

A 12600x9000 mechanical drawing page (`Floor_2A` at 300 DPI) and a 1935x595
floor-overview screenshot were probed through the same path. Both returned
valid empty results (`{"equipment":[]}`) because the endpoint's 900-pixel
resize makes their text unreadable. The model did not hallucinate on
unreadable input. Mechanical-drawing extraction requires tiling or cropping
work scheduled after W3 (`data/snapshots/w03/probe_drawing_equipment.csv`).

### Remaining W3 closure items

The following work remains after this commit:

* Post representative raw extraction results and accuracy observations to
  Teams.
* Replace the temporary Colab and quick-tunnel endpoint with a repeatable GPU
  deployment when infrastructure is available.
* Tiling or cropping for mechanical drawings and floor overviews (W4+).

The current batch runner uses bounded concurrent independent requests. It is not
a provider-native asynchronous discounted batch API.

No W3 extraction output is written directly to PostgreSQL. Human review and later
pipeline stages remain required before database publication.
