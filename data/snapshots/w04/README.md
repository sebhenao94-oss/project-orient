# W4 Snapshots — Floor 02

Committed, sanitized W4 evidence. Raw provenance (run JSONL with machine paths)
stays under `data/extractions/w04/` and is gitignored, matching the W3
convention. The committed `relationships_floor_02.json` still carries per-edge
provenance (`source_drawing`, `source_sha256`), so committing the verbose run
JSONL is unnecessary.

## `floor_ambiguous_contexts.csv`

The 7 ventilation contexts that sit under the `Floor_02/` topic path but carry a
`_1_` token in their unit name (`EAVAV_1_01/04`, `OAVAV_1_02/03/04/05/07`). The
topic path says Floor 2, but the naming convention's post-type digit says
Floor 1, and the W3 drawings label these units `_02_`. Metadata has no floor
field, so this is genuinely ambiguous — likely the supervisor's deliberate
floor-distinction test.

**Required Track B handling:** these rows are NOT flagged in the immutable W3
`topics_equipment_floor_02.csv` (they look clean there). Normalisation /
discrepancy generation must carry `status=floor_ambiguous` for them and route
them to review rather than treating them as settled Floor-2 equipment. Do not
silently drop or silently keep. A supervisor clarification is pending.

## `normalized_equipment_floor_02.csv`

Track B reconciliation of the two immutable W3 snapshots into a single canonical
Floor-02 equipment list plus a discrepancy/gap report, produced by
`pipeline/normalization.py`. The module is read-only on its inputs and calls no
model endpoint.

It matches the topics-derived snapshot (`topics_equipment_floor_02.csv`, the
BMS's own record) against the drawing-derived snapshot
(`drawing_equipment_floor_02.csv`, the model's reading of the graphics) on a
separator- and zero-padding-insensitive **canonical key** (`AHU-02A`,
`AHU 02 A`, and `AHU_02A` all key to `AHU_02A`; `OAVAV_2_01` and `OAVAV_02_01`
both key to `OAVAV_2_1`). The key deliberately preserves the
floor-distinguishing digit, so a `_1_` unit and a `_2_` unit never collapse —
that distinction is the contested-floor question.

Each unit is classified by `discrepancy_category`:

- `matched` — present in both sources with a consistent type (`status=settled`).
- `type_mismatch` — present in both but inferred types disagree (review).
- `topics_only` — in the BMS topics but absent from drawing evidence (gap).
- `drawing_only` — extracted from drawings but absent from the BMS topics (gap;
  catches model misreads such as `DAWNV_2_09`/`EVAV_02_1`).
- `floor_ambiguous` — one of the seven contested-floor units above. This
  overrides any apparent match: the unit is carried with `status=floor_ambiguous`
  and routed to review, never silently settled, per the handoff requirement.

Current Floor-02 result over the 37 topic contexts + 30 drawing units (56 union):
**11 matched, 19 topics_only, 19 drawing_only, 7 floor_ambiguous, 0
type_mismatch**; 45 units routed to review. The 37 topic contexts reconcile
exactly (11 matched + 19 topics_only + 7 floor_ambiguous), so every BMS context
is accounted for.

Regenerate with:

```powershell
py -m pipeline.normalization --overwrite
```

### Revisit as more LLM extractions land

The canonical key is a general rule (separator/zero-padding/device-prefix
insensitive), so it handles unseen variants of those kinds automatically. It was
only *validated* against the current Floor-02 snapshots, though, and does not yet
cover some variation classes that more extractions are likely to expose:

- mixed alphanumeric padding (`02A` vs `2A` do not currently match);
- equipment-type spelling variants / model misreads (`EVAV` vs `EAVAV`,
  `DAWNV` vs `OAVAV` are treated as distinct);
- different name segmentation than the cleaned `llm_proposed_canonical_name`.

These currently fail *safe* — they surface as `topics_only`/`drawing_only` gaps
(over-flagged for review) rather than silent false merges. As more floors and
re-runs accumulate, review the gap rows for cases that are really the same unit
and extend `canonical_key()` (and possibly a small type-synonym map) to cover
them. Treat any type-synonym normalisation cautiously: collapsing misreads like
`EVAV`/`DAWNV` would *hide* exactly the extraction errors this report is meant to
surface.

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

## `canonical_equipment_floor_02.csv`

The normalised Floor-02 equipment list with the team-lead naming convention
`{Type}_{floor}-{unit}` applied and the type mapped onto the current vocabulary
(the supervisor's `equipments_point_types/` library + the brief Appendix A).
Produced by `pipeline/discrepancy.py` as an additive downstream stage over
`normalized_equipment_floor_02.csv` — it does not modify the normalization layer.

Type mapping uses a best-guess-base + review-flag policy
(`pipeline/equipment_vocab.py`): confident mappings (AHU, VAV, FCU, OAVAV, EAVAV)
carry no flag; `VAVRH -> VAV-RH-HW` and `FPTU` (subtype unresolved) are flagged.
The convention name is only asserted when the label clearly matches its inferred
type and floor; **misreads** (`DAWNV`, `EVAV`) and **contested-floor** (`_1_`)
units keep their unique canonical key rather than being renamed, and any residual
name collision falls back to the key — so `canonical_name` is always unique and
no extraction error is silently cleaned up.

## `discrepancy_report_floor_02.csv` — the primary W4 gap report

The brief-mandated discrepancy report, keyed by
`(building, floor, equipment_type, equipment_id)` with columns
`in_points, in_drawings, status, evidence_point, evidence_drawing,
severity_hint`. Produced by `pipeline/discrepancy.py`.

`status` ∈ `matched, missing_from_drawings, missing_from_points,
partial_coverage, identifier_mismatch, type_mismatch, relationship_gap,
floor_ambiguous`. `severity_hint` ∈ `high` (AHU/plant), `medium` (terminal),
`low` (matched / id-only). It is a sort hint for the review UI, not a final
ranking — detection only, no resolution.

Current Floor-02 result (56 rows): **11 matched, 19 missing_from_drawings
(4 high = AHUs, 15 medium), 19 missing_from_points (medium), 7 floor_ambiguous
(medium)**. `relationship_gap` rows are not produced because 0 serving
relationships were extracted (see above).

## `graph_validation_floor_02.json`

Output of the relationship graph validator (`pipeline/graph_validator.py`) run
over `relationships_floor_02.json` against `canonical_equipment_floor_02.csv`.
Checks: `unknown_node`, `multiple_air_parents`, `cycle`, `ref_type_sanity`
(errors); `orphan_terminal` (informational); low-confidence/`conflict`
(review items). `passed` is true when there are no error-level findings.

Current result: **0 edges, passed=true, 0 errors, 50 orphan terminals** — every
terminal is trivially an orphan because no serving relationships were extracted.
The validator is exercised on real edges by the offline tests (the Floor-1
worked example passes; each error mode has a fixture).
