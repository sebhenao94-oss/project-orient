# Project ORIENT - Week 2 Ingestion Pipeline

Project ORIENT is an ingestion pipeline for S3-based Building Management System
(BMS) screenshots, control drawings, and mechanical drawing files. This Week 2
implementation focuses on the data engineering foundation: finding source files
in S3, downloading them locally, preparing image/PDF inputs, routing low-quality
images for review, and writing a local/S3 manifest for the run.

## Current Functionality

- Reads `S3_BUCKET`, `S3_INPUT_PREFIX`, and `S3_OUTPUT_PREFIX` from the project
  root `.env` file.
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
- Checks image quality using configurable width/height thresholds in
  `pipeline/ingestion.py`.
- Converts PDFs to PNG page images at 300 DPI.
- Uploads passed-quality images to `processed/`.
- Uploads failed-quality images to `review/failed_quality/`.
- Writes a local run manifest to `tmp/orient/manifest.json`.
- Uploads a timestamped manifest to `S3_OUTPUT_PREFIX/manifests/`.

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
