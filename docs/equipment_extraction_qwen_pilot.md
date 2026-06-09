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


## Development Hold-Out OAVAV v2 Pilot

`OAVAV_02_01.png` was held out from the local five-shot prompt examples for this
development experiment. The image was already available to the development team
and was manually reviewed before inference. This was not the supervisor's
official unseen held-out evaluation dataset, and it must not be described as an
official benchmark, production evaluation, or final accuracy result.

### Target And Expected Result

- Target image: `OAVAV_02_01.png`.
- Original image dimensions: `2567 x 733`.
- The image remained outside `v2_few_shot_examples.json`.
- Human-reviewed expected in-scope equipment:

```json
{"equipment":[{"raw_label":"OAVAV_02_01","canonical_name":"OAVAV_02_01","equipment_type":"OAVAV"}]}
```

Scope interpretation:

- `OAVAV_02_01` is in scope as an ATU/VAV-family equipment unit.
- `DOAS_22_1` is visibly present in the image but is excluded from the expected
  Project ORIENT equipment response because the project brief limits evaluated
  equipment extraction to AHU, ATU/VAV-family equipment, and FCU.
- Ventilation/outside-air equipment outside that evaluated taxonomy is out of
  scope for equipment extraction and evaluation.
- `DOAS_22_1` must not be converted to `AHU`, `unknown`, or another supported
  type merely to retain it.
- The original image evidence remains preserved even when an out-of-scope label
  is excluded from the equipment candidate list.
- Visible point, status, configuration, command, setpoint, and measurement
  labels are also excluded from the equipment response.

Visible non-equipment labels included `Airflow`, `Eff Airflow Sp`, `Dmpr Resp`,
`Max Airflow Sp`, `Dmpr Ovr`, `Occ Sts`, `KFactor`, and `System Enable`.

### Runtime

- Runtime: Google Colab.
- GPU: Tesla T4.
- Model: `Qwen/Qwen3-VL-2B-Instruct`.
- Inference implementation: direct Hugging Face Transformers inference.
- Model class: `Qwen3VLForConditionalGeneration`.
- Processor class: `Qwen3VLProcessor`.
- Model device: `cuda:0`.
- Approximate allocated GPU memory after model load: `4.26 GB`.
- No persistent endpoint was used.
- vLLM was not used for this experiment.
- Generation was deterministic with `do_sample=False`.

This experiment did not use a production service, OpenAI-compatible endpoint,
batch API, or persistent cloud deployment.

### Run 1 - v2 Zero-Shot Baseline

This run used the committed v2 system prompt, the committed v2 user-template
text, the original full-resolution target image, no few-shot example images, and
no expected assistant-response examples.

Observed behavior:

- The response included out-of-scope `DOAS_22_1`.
- It returned unsupported equipment type `HVAC`.
- It returned `OAVAV_02_01` repeatedly.
- It used Markdown JSON fences.
- Generation entered a repetitive-output pattern.
- The captured response was incomplete or truncated.
- It assigned confidence `0.99` despite major extraction and schema errors.

The captured output is not reconstructed here because generation became
repetitive and the captured response was incomplete.

Interpretation:

- The zero-shot prompt alone was not reliable enough for this image.
- High confidence did not correspond to correctness.
- Allowed-type validation, repeated-label suppression, JSON validation, and
  human review remain necessary.

### Run 2 - Resized Five-Shot Test

This run used the committed five v2 few-shot examples, the expected assistant
responses from the committed v2 manifest, five example images resized so that
their maximum dimension was `1024` pixels, the development hold-out target
resized from `2567 x 733` to `1024 x 292`, and deterministic generation with
`do_sample=False`.

Observed response:

```json
{"equipment":[{"raw_label":"GAVAV_02_01","canonical_name":"GAVAV_02_01","equipment_type":"GAVAV","confidence":0.99}]}
```

Observed improvements:

- Returned one equipment candidate.
- Excluded out-of-scope `DOAS_22_1`.
- Avoided repeated output.
- Returned the required top-level `equipment` object.
- Did not use Markdown fences.
- Did not include extra prose.

Remaining failures:

- Misread `OAVAV_02_01` as `GAVAV_02_01`.
- Returned unsupported type `GAVAV`.
- Assigned confidence `0.99` despite the OCR and classification error.

Interpretation:

- The five-shot examples materially improved output structure, scope filtering,
  repeated-label suppression, and brevity.
- Resizing the very wide target image to only `292` pixels in height likely
  reduced the visual resolution of the title and caused the OCR error.
- A generic maximum-dimension-only resize policy can be harmful for wide BMS
  screenshots.

The resize explanation is the most plausible interpretation supported by the
comparison, not proven causation.

### Run 3 - Hybrid Five-Shot Success

This run used the same committed v2 system prompt, the same committed v2 user
template, the same five committed few-shot expected responses, five example
images resized to a maximum dimension of `1024` pixels, the original
full-resolution target image at `2567 x 733`, deterministic generation with
`do_sample=False`, and a lower output-token limit sufficient for the expected
compact JSON response.

Observed response:

```json
{"equipment":[{"raw_label":"OAVAV_02_01","canonical_name":"OAVAV_02_01","equipment_type":"OAVAV","confidence":0.99}]}
```

The response matched the human-reviewed expected result:

- Correct raw label: `OAVAV_02_01`.
- Correct canonical-name candidate: `OAVAV_02_01`.
- Correct supported equipment type: `OAVAV`.
- Exactly one distinct equipment candidate.
- Excluded out-of-scope `DOAS_22_1`.
- Excluded point-level and non-equipment labels.
- Returned the required top-level JSON object.
- Included all four required fields.
- Used a numeric confidence value.
- Did not use Markdown fences.
- Did not include extra prose.
- Did not repeat the equipment identifier.

The `0.99` confidence was model-produced. The successful result does not prove
that the model's confidence is calibrated. Human review remains required.

### Performance And Resource Observation

Attempting the five-shot run with all six original full-resolution images caused
the Colab execution to become extremely slow or unresponsive during vision
processing. The execution was interrupted while operating in the model's
convolutional vision path. The model and processor remained loaded after
interruption. Approximate allocated GPU memory after interruption was `4.64 GB`.

Resizing only the example images reduced the inference workload enough for the
experiment to complete. Keeping the target image at adequate resolution preserved
title readability in the successful run. No exact runtime was measured. The
resized five-shot and hybrid runs completed in practical development time, while
the all-full-resolution attempt did not complete normally.

### Development Hold-Out Conclusions

1. The development hold-out success supports continued use of the committed v2
   all-visible-equipment prompt and five-shot examples.
2. The zero-shot result was not reliable enough for production use on this image.
3. Five-shot context improved schema adherence, supported-scope filtering,
   repeated-label suppression, and response concision.
4. Target-image resolution materially affected OCR accuracy in this experiment.
5. Reference images may be resized to manage visual-token and GPU cost, but the
   target image must retain enough resolution for small equipment identifiers.
6. A universal maximum dimension of `1024` pixels is not appropriate for every
   wide BMS screenshot because it can reduce image height and text scale too
   aggressively.
7. Future preprocessing should use a text-preserving policy, potentially
   considering minimum target height, minimum text scale, aspect ratio,
   layout-aware candidate regions, selective cropping, and tiling for dense
   drawings.
8. Crops or resized inference copies supplement the original image; they do not
   replace the original full-resolution image as authoritative source evidence.
9. The successful development hold-out result is one controlled example, not
   proof of general production accuracy.
10. Broader evaluation is still required across multiple equipment types,
    multiple BMS layouts, multi-equipment screenshots, mechanical drawings,
    difficult OCR cases, and out-of-scope contextual labels.
11. Pydantic response validation, allowed-enum validation, parsing cleanup,
    confidence review, and human approval remain mandatory.
12. High model confidence must not be treated as proof that an extraction is
    correct.
13. The supervisor's official unseen held-out evaluation remains a separate
    future milestone.

## Conclusion

One full-image call is not reliable enough for production completeness.
Production direction is full-image preservation plus layout-aware candidate
regions, candidate merging, within-image repeated-label suppression, JSON
cleanup, Pydantic validation, and human review.

Large images and dense mechanical drawings may require resizing, cropping, or
tiling before inference. Production preprocessing, client orchestration, and
review routing remain future work.
