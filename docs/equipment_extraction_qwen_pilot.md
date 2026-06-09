# Equipment Extraction Qwen Pilot

## Purpose

Record sanitized findings from temporary Project ORIENT equipment-extraction
pilot work using Qwen vision-language inference. This document contains no
credentials, URLs, tokens, absolute local paths, or image binaries.

## Environment

- Temporary runtime: Google Colab Tesla T4.
- Model: `Qwen/Qwen3-VL-2B-Instruct`.
- Inference mode: direct Hugging Face Transformers inference.
- Endpoint status: no persistent endpoint was created for this pilot.

## Pilot Findings

- Full-page AHU inference succeeded.
- Full-page VAV inference failed by selecting contextual AHU evidence and
  missing the page-title VAV equipment.
- Focused title crops recovered VAV, VAVRH, FPTU, FCU, and OAVAV titles.
- FCU initially lost its unique identifier in `canonical_name`.
- Full-image all-visible tests found contextual labels but also showed duplicate
  outputs, missed page-title equipment, bare arrays, Markdown fences, missing
  confidence fields, incorrect unknown classification, and high-confidence
  incorrect outputs.
- Combining full-image and focused-region evidence recovered `VAV_2_05` plus
  `AHU 02 A` in the manual experiment.
- `OAVAV_02_01` was a held-out title-crop/five-shot pilot image, but it was not
  a complete all-visible-equipment benchmark.

## Conclusion

One full-image call is not reliable enough for production completeness.
Production direction is full-image preservation plus layout-aware candidate
regions, candidate merging, within-image repeated-label suppression, JSON
cleanup, Pydantic validation, and human review.

Large images and dense mechanical drawings may require resizing, cropping, or
tiling before inference. Production preprocessing, client orchestration, and
review routing remain future work.
