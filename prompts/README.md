# Prompts

Prompts are versioned Project ORIENT artifacts. Each prompt folder should keep
its templates, few-shot manifests, and usage notes together so model behavior can
be reviewed before client integration.

Current prompt areas:

- [Equipment extraction](equipment_extraction/) - vision prompt artifacts for
  extracting HVAC equipment labels from BMS graphics and drawings.
- [Topic to unique equipment](topic_to_unique_equipment/) - text prompt
  artifacts for parsing raw BMS `topic_name` paths into unique equipment units
  with review flags.

Shared generated context:

- `equipment_type_context.md`: generated list of equipment classes from
  `equipments_point_types/*.py`. Regenerate it with
  `python -m pipeline.generate_equipment_type_context` after changing the
  equipment library.
