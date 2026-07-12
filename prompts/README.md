# Prompts

Prompts are versioned Project ORIENT artifacts. Each prompt folder should keep
its templates, few-shot manifests, and usage notes together so model behavior can
be reviewed before client integration.

Current prompt areas:

- [Equipment extraction](equipment_extraction/) - vision prompt artifacts for
  extracting HVAC equipment labels from BMS graphics and drawings.
- [Relationship mapping](relationship_mapping/) - evidence-gated serving-ref
  prompts over normalized equipment plus drawing context.
- [Relationship graphics](relationship_graphics/) - linked-widget extraction
  prompts for BMS graphic pages.
- [`equipment_type_context.md`](equipment_type_context.md) - generated,
  type-names-only classification context shared by equipment vision paths.
