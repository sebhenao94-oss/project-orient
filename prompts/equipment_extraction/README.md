# Equipment Extraction Prompts

This directory contains the single current-best prompt package used by
`pipeline.equipment_prompts` and `pipeline.extraction`.

## Current files

- `v4_system.md` — extraction policy for screenshots and cropped drawing tiles.
- `v4_user_template.md` — target-image instruction.
- `v4_few_shot_examples.json` — three reviewed screenshot examples. The image
  binaries are local inputs and are intentionally not committed.

The simplified type-name list in `../equipment_type_context.md` is appended to
the system prompt by default. It deliberately omits point-type payloads that do
not help equipment extraction.

## As-built behavior

The loader validates the prompt files, example manifest, expected JSON, and
example image paths before a model request. Screenshot requests include the
three few-shot examples. Full-resolution drawing tiles omit screenshot examples
because they are off-domain and expensive to resend per tile; the v4 system
prompt contains the drawing-tile rules.

Extraction returns only equipment candidates. Point labels, zones, components,
relationships, canonical approval, cross-image deduplication, and review
decisions belong to downstream stages. Source/PDF provenance is carried by the
Stage 1 prepared-record manifest rather than embedded in the model response.

Prompt content and example-image bytes participate in checkpoint fingerprints,
so editing these current-best files in place invalidates stale successful
results even though the semantic `equipment_extraction_v4` label stays stable.

## History

Earlier v1–v3 experiments are preserved in Git history, not as parallel prompt
files. Their findings and the rationale for v4 are summarized in
[`docs/HISTORY.md`](../../docs/HISTORY.md). Use Git commits to document future
iterations while keeping this directory as the runnable current state.
