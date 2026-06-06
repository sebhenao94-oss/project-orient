"""Raw equipment extraction for Project ORIENT Week 3.

This module will process prepared BMS screenshots and mechanical-drawing
images using a vision-capable LLM.

Week 3 responsibilities:
- Extract equipment labels visible in each source image.
- Identify the source floor and retain Floor 02 equipment only.
- Classify raw equipment types such as AHU, FCU, VAV, VAVRH, FPTU,
  OAVAV, and unresolved project-specific types.
- Preserve source filename, source type, evidence detail, and confidence.
- Write versioned raw extraction snapshots under data/snapshots/w03/.

This module must not:
- Write equipment directly to the production database.
- Resolve discrepancies between drawings and database topics.
- Deduplicate or finalize canonical equipment names.
- Infer AHU-to-terminal relationships.

Normalization, deduplication, discrepancy analysis, and relationship mapping
belong to the Week 4 pipeline stages.
"""
