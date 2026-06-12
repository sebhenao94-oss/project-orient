# Equipment Extraction Prompts

This folder contains versioned prompt artifacts for reading equipment labels from
BMS screenshots and drawing images.

## Files

- `v1_system.md`: historical primary-page equipment baseline.
- `v1_user_template.md`: reusable v1 user message.
- `v1_few_shot_examples.json`: v1 few-shot manifest.
- `v2_system.md`: historical all-visible-distinct-equipment prompt.
- `v2_user_template.md`: reusable v2 user message.
- `v2_few_shot_examples.json`: v2 few-shot manifest based on human-reviewed
  BMS screenshot results.
- `v3_system.md`: current all-visible prompt with hardened few-shot-leakage
  rules and explicit navigation-tree/table guidance.
- `v3_user_template.md`: reusable v3 user message.
- `v3_few_shot_examples.json`: v3 few-shot manifest reduced to three examples.

## Version Semantics

v1 is retained unchanged as the historical primary-page baseline. It focuses on
the equipment represented by the BMS graphics page title and intentionally
ignores contextual or upstream equipment labels.

v2 is the current all-visible-distinct-equipment interpretation. It inspects the
complete image and returns every distinct, clearly visible, in-scope HVAC
equipment identifier, including contextual, upstream, or neighboring labels when
they identify concrete equipment units.

Point-level and non-equipment labels are excluded only from the equipment
candidate list. They are not deleted from the source image or from the overall
pipeline. Measurements, commands, sensors, statuses, setpoints, alarms, rooms,
zones, and generic component labels remain available for later
point-classification, relationship-mapping, or zone-orientation stages. Generic
components means labels such as fan, filter, damper, or coil when they do not
identify a distinct in-scope equipment unit.

The original full image is authoritative and must be preserved. Focused crops or
candidate regions may supplement full-image inference, but they must not replace
the full image or discard other visible evidence. Fixed crop coordinates are not
a universal assumption.

Region results may later be merged and validated by the client/orchestration
layer. Repeated appearances of the same identifier within one image should
produce one candidate. Cross-image deduplication remains a later pipeline stage.
Relationship roles such as upstream, downstream, parent, or child also remain a
later pipeline stage.

Mechanical drawings may require tiling and may contain many equipment labels.
Malformed JSON cleanup, Markdown-fence cleanup, schema validation, and region
merging belong to future client/orchestration work.

## Future Client Assembly

A future Project ORIENT client should assemble few-shot messages as follows:

1. Load the selected versioned system prompt as the system message.
2. Load each externally supplied example image using `image_filename` from the
   matching few-shot manifest.
3. Pair each example image and `user_text` with `expected_response` as the
   assistant message.
4. Add the new target image using the matching user template.

Image binaries are intentionally not committed. The filenames in the manifests
refer to external development assets supplied to the client or orchestration
layer.

`canonical_name` is a conservative normalization candidate. Final canonical-name
approval belongs to later normalization and human-review stages.

Low-confidence routing, including the 0.75 review threshold, belongs to
downstream orchestration. It is not part of the prompt schema.

Source provenance is retained by the client or orchestration layer rather than
being added to `EquipmentExtractionResponse`.

Floor 02 filtering belongs to input selection and orchestration because `floor`
is not part of the extraction response contract.

The current v2 examples cover `AHU`, `VAV`, `VAVRH`, `FPTU`, `FCU`, and `OAVAV`
through all-visible screenshot evidence.

## Approved v1 Examples

- `AHU_02A.png`: primary title `AHU 02 A`, output type `AHU`.
- `VAV_2_05.png`: primary title `VAV_2_05`, output type `VAV`; contextual
  `AHU 02 A` must not be returned in v1.
- `VAVRH_2_1.png`: primary title `VAVRH_2_1`, output type `VAVRH`; neighboring
  VAVRH table rows must not be returned.
- `fptu_2_01.png`: primary title `FPTU_2_01`, output type `FPTU`; contextual
  `AHU 02 A` must not be returned in v1.
- `fcu_02_1.png`: primary title `FCU_02_1`, output type `FCU`; contextual
  `OAVAV_02_04` must not be returned in v1.

## Version 3 Rationale

The June 11, 2026 independent live pilot (`ahu_02c.png`, an image not present in
the few-shot set) exposed two v2 failures on Qwen3-VL-2B:

1. The example labels `FPTU_2_01` and `FCU_02_1` were copied from the
   demonstrations into the target result at 0.99 confidence even though
   neither label is visible in the target image.
2. Only 3 of roughly 24 visible in-scope identifiers were returned.

v3 responds structurally rather than with more prompt prose:

- The few-shot set is reduced from five examples to three (`AHU_02A.png`,
  `VAV_2_05.png`, `VAVRH_2_1.png`), removing the two leaked labels from the
  context entirely. Three examples remain within the brief's 3-5 requirement.
- Navigation menus, equipment trees, and summary table rows are called out as
  valid identifier sources.
- An explicit omit-when-uncertain rule was added.

Known v3 limitation observed in the June 11 Floor 02 batch: the remaining
example label `VAVRH_2_1` still leaked onto several target pages where it is
not visible. Few-shot label leakage appears to be a model-capacity behavior
that prompt wording reduces but does not eliminate at the 2B scale. Leaked
rows remain in raw snapshots by design and are routed to W4
normalization/deduplication and human review.

v3 type coverage through examples is AHU, VAV, and VAVRH; FPTU, OAVAV, and FCU
typing relies on the mechanical prefix mappings.

## Approved v2 Examples

- `AHU_02A.png`: returns `AHU 02 A`.
- `VAV_2_05.png`: returns `VAV_2_05` and one `AHU 02 A` candidate even though
  the AHU label appears more than once.
- `VAVRH_2_1.png`: returns `VAVRH_2_1` and excludes point/status fields.
- `fptu_2_01.png`: returns `FPTU_2_01` and `AHU 02 A`.
- `fcu_02_1.png`: returns `FCU_02_1` and `OAVAV_02_04`.
