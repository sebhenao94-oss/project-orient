# relationship_graphics — serving topology from BMS graphic pages

Current-best version: **v1** (validated 2026-07-02).

## Why this package exists

The mechanical floor plans are a weak source for the serving hierarchy: the W6
full-resolution tiling run over both Floor-2 sheets recovered exactly **1
conflict-flagged airRef** (see `docs/relationship_graphics_findings.md`). The BMS
graphic pages, however, embed the topology directly: each terminal's page carries
**linked equipment widgets** — small titled boxes naming the unit's upstream
equipment and mirroring a few of its live points (a VAV page carries an
"AHU 02 A" box with DA Temp / DA Flow; an FCU page carries its upstream
`OAVAV_02_xx`; an OAVAV page carries `DOAS_22_1`). The BMS integrator configured
those links per unit — reading them recovers the serving graph. One pass over the
22 Floor-2 screenshots produced **47 candidate edges** vs the plan-geometry
approach's 1.

This prompt does NOT ask the model to infer relationships. It asks it to
**transcribe relationship evidence** — the extraction stays mechanical, and the
inference (evidence → edges, confidence, extrapolation) happens deterministically
in `pipeline/graphics_relationships.py`, where it is testable.

## Evidence the model reports per page

- `page_title` — authoritative over the screenshot filename (filenames drift:
  `fptu_02_3.png` is page `FPTU_2_03`).
- `linked_widgets[]` — label, points shown, and `values_live` (dashed values =
  unit offline, but the link itself is still structural BMS configuration).
- `water_valves` — CHW/CHWR/CHWS = chilled water; **WW/WWR/WWS = warm (hot)
  water** (models miss this without the hint).
- `nav_tree_items` / `summary_table_rows` — **inventory evidence only**. The nav
  tree groups by equipment type, not by AHU, and summary tables are global type
  lists; neither is serving evidence (this mirrors the negative example in
  `relationship_mapping/v2`).
- Floor-overview pages (many unit chips on a plan) report chips as inventory,
  never as linked widgets.

## Validation record (v1)

Dual-pass check on 2026-07-02: an in-session Claude read and an API run
(`claude-sonnet-4-6`, ~$0.21 for 23 images) agreed on **14/14 serving links**.
Divergences were one page-title character misread (`OAVAV_02_01` → `QAVAV_02_01`,
caught by canonical-key normalization → review) and one mis-attributed valve on
`VAVRH_2_1` (routed to review). Few-shot examples below are drawn from the
verified pass; the referenced images live in `downloads/Floor_2/` (populate via
`scripts/populate_downloads.py`).

## Files

- `v1_system.md` — system prompt (task, widget definition, domain notes)
- `v1_user_template.md` — per-image user message
- `v1_few_shot_examples.json` — verified screenshot → evidence-JSON pairs
