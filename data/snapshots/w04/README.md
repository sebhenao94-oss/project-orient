# W4 Snapshots — Floor 02

Committed, sanitized W4 evidence. Raw provenance (run JSONL with machine paths)
stays under `data/extractions/w04/` and is gitignored, matching the W3
convention.

## `relationships_floor_02.json`

Drawing-derived equipment-to-equipment relationships for Floor 02, produced by
`pipeline/relationships.py` with prompt `relationship_mapping_v2` against the
available BMS screenshots.

**Result: 0 documented serving relationships** across 22 Floor-02 screenshots
(21 eligible; the 595 px floor-overview was quality-gated out).

This empty result is correct, not a failure. The single-equipment BMS graphics
pages show one unit's graphic plus a side navigation menu that lists other floor
equipment. That menu is a site navigation aid, **not** a serving hierarchy, so
there is no drawn duct/pipe or schedule on these pages that documents which AHU
serves which terminal. The high-precision v2 prompt therefore returns no edges
rather than inventing them.

### Why (and the v1 -> v2 fix)

The first live pilot (`ahu_02c.png`, prompt v1) returned 33 `airRef` edges all
pointing to the page's AHU and truncated at the model token cap: it had
connected every unit in the navigation menu to the page's AHU. Prompt v2 states
that navigation panels/trees/menus are not evidence, requires a drawn or
scheduled serving connection per edge, adds a negative example, and emits compact
JSON. Re-piloting the same image with v2 returns an empty list in ~5 s.

### Where the real evidence is

Serving relationships (`airRef`, and the water references
`chilledWaterRef`/`hotWaterRef`/`condenserWaterRef`) are documented on the
**mechanical drawings**, which are unreadable at the current inference
endpoint's image-resize cap. Reading them requires a tiling/crop pass, deferred
beyond W4. Relationships are the secondary W4 goal; the gap report is primary.

The Floor-1 worked example in `equipment_details` (6 rows: `AHU_1-01` with its
reheat terminals via `airRef` and CHW/HW plants via water refs) is the reference
for the target relationship shape once drawing evidence becomes readable.

### Schema

```text
snapshot_version, property_id, property_name, floor, prompt_version, model_id,
relationship_count, relationships[]
```

Each relationship edge (when present) carries:
`child, parent, ref_type, confidence, conflict, conflict_reason, source_drawing,
source_sha256, review_required, review_reason`. `ref_type` is one of
`airRef, chilledWaterRef, hotWaterRef, condenserWaterRef, systemRef`
(`spaceRef`/`floorRef` reserved for later zone work). `review_required` is set
when confidence < 0.75 or `conflict` is true.
