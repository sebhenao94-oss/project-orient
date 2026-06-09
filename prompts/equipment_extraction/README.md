# Equipment Extraction Prompts

This folder contains the versioned v1 prompt artifacts for reading equipment
labels from BMS screenshots and drawing images.

## Files

- `v1_system.md`: system instructions for the equipment-extraction task.
- `v1_user_template.md`: reusable user message for each independent target
  image request.
- `v1_few_shot_examples.json`: machine-readable few-shot manifest with logical
  image filenames and verified expected outputs.

## Future Client Assembly

A future Project ORIENT client should assemble few-shot messages as follows:

1. Load `v1_system.md` as the system message.
2. Load each externally supplied example image using `image_filename` from
   `v1_few_shot_examples.json`.
3. Pair each example image and `user_text` with `expected_response` as the
   assistant message.
4. Add the new target image using `v1_user_template.md`.

Image binaries are intentionally not committed. The filenames in the manifest
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

The current five examples cover `AHU`, `VAV`, `VAVRH`, `FPTU`, and `FCU`.
`OAVAV` remains an allowed output type despite not having a v1 few-shot example.

## Approved v1 Examples

- `AHU_02A.png`: primary title `AHU 02 A`, output type `AHU`.
- `VAV_2_05.png`: primary title `VAV_2_05`, output type `VAV`; contextual
  `AHU 02 A` must not be returned.
- `VAVRH_2_1.png`: primary title `VAVRH_2_1`, output type `VAVRH`; neighboring
  VAVRH table rows must not be returned.
- `fptu_2_01.png`: primary title `FPTU_2_01`, output type `FPTU`; contextual
  `AHU 02 A` must not be returned.
- `fcu_02_1.png`: primary title `FCU_02_1`, output type `FCU`; contextual
  `OAVAV_02_04` must not be returned.
