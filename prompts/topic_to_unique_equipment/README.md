# Topic To Unique Equipment Prompts

Versioned text-only prompts for parsing raw BMS `topic_name` paths into a unique
equipment list with review flags.

This prompt package exists because deterministic parsing works for the current
known pattern:

```text
Floor_02/DEV123_AHU_1_01/POINT_NAME
```

but may fail when another building uses a different path structure. The LLM task
is to infer likely equipment units from the complete topic path, group spelling
variants, and flag uncertain cases rather than silently dropping or merging them.

## Files

- `v1_system.md`: current topic-name parsing system prompt.
- `v1_user_template.md`: user template with the `<<TOPIC_NAMES>>` placeholder.
- `v1_few_shot_examples.json`: text-only examples covering duplicate
  zero-padding, type-token typo review, non-equipment paths, and unfamiliar path
  structures.
- `../equipment_type_context.md`: shared generated equipment type list from
  `equipments_point_types/*.py`.

Regenerate the equipment context after changing `equipments_point_types/`:

```bash
python -m pipeline.generate_equipment_type_context
```

When calling the LLM, include `v1_system.md` plus the shared
`../equipment_type_context.md` context before the rendered user template. The
context file tells the model which strings are equipment types and prevents it
from inventing unsupported equipment classes.

## Output Contract

The model returns one JSON object:

```json
{
  "equipment": [],
  "unparsed_topic_names": []
}
```

Each equipment row includes `canonical_name`, `equipment_type`,
`raw_equipment_labels`, `source_topic_names`, `floors`, `confidence`,
`equipment_type_confidence`, `review_required`, and `review_reason`.

`confidence` describes confidence in the extracted equipment identity/name.
`equipment_type_confidence` describes confidence that the assigned
`equipment_type` is the correct class from the shared generated equipment type
context. For example, the model may be confident that `FPTU_2_01` is an
equipment name while still having low type confidence because the exact FPTU subtype
(`FPTU-PARALLEL-HW`, `FPTU-SERIES-ELEC`, etc.) is not clear from topic names
alone.

## Existing Non-LLM Rules

Before this prompt package, topic-name handling was deterministic:

- `pipeline/extraction.py` grouped known topic paths by the second segment of
  `Floor_02/<equipment_context>/<point_name>`.
- `pipeline/normalization.py` already normalized separator and zero-padding
  variants such as `AHU_01_1` and `AHU_1_01` to the same match key.
- `pipeline/topic_to_unique_equipment.py` applies those deterministic ideas to a
  topic-name CSV and emits a review CSV.

Use this prompt package when path structures vary enough that deterministic
rules are too brittle.
