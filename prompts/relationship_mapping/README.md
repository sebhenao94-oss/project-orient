# Relationship Mapping Prompts

Versioned prompt artifacts for inferring equipment-to-equipment relationships
from BMS graphics and mechanical drawings, expressed as Haystack reference edges.

## Files

- `v1_system.md` / `v1_user_template.md` / `v1_few_shot_examples.json`: the
  initial package (one positive worked example).
- `v2_system.md` / `v2_user_template.md` / `v2_few_shot_examples.json`: current
  package. Adds an explicit "navigation panels are not relationships" rule, an
  evidence requirement (drawn duct/pipe or schedule), a negative few-shot
  example, and a compact single-line JSON instruction.

Each `*_user_template.md` contains the `<<EQUIPMENT_LIST>>` placeholder, into
which the orchestration layer injects the normalised equipment list for the
target image.

## Version 2 rationale

The first live relationship pilot (`ahu_02c.png`) returned 33 `airRef` edges all
pointing to `AHU_02C` and truncated at the endpoint token cap. The model had
connected every unit in the page's left-hand navigation menu to the page's AHU.
That menu is a site navigation list, not a serving hierarchy — and v1's positive
example, which described terminals as "nested under" the AHU, reinforced the
wrong heuristic. v2 responds by:

- stating that navigation panels / equipment trees / menus are not evidence of a
  serving relationship;
- requiring direct serving evidence (a drawn duct/pipe/airflow path or an
  explicit schedule) for every edge;
- reframing the positive example's evidence as a mechanical schedule rather than
  tree nesting;
- adding a negative example (a navigation-only page → `{"relationships":[]}`);
- requiring compact single-line JSON to reduce truncation.

## Design

The relationship task takes a **normalised equipment list (text) + one image**
and returns edges only between equipment in that list.

Two deliberate differences from `prompts/equipment_extraction/`:

1. **Few-shot examples are text-only** (no demonstration images). v1 is seeded
   from the supervisor's Floor-1 worked example in `equipment_details` (units
   `AHU_1-01`, `VAVRH_1-01`, `VAV-RH-HW_1-01`, plants `HW/CHW/COND-PLANT_1`),
   for which we hold the authoritative edges but not a matching image. Text
   demonstrations also avoid the image few-shot-leakage failure mode found in
   W3 equipment extraction.
2. **The single target message carries both the equipment list and the image.**

## Reference vocabulary

`ref_type` mirrors the live `equipment_details` reference columns:
`airRef`, `chilledWaterRef`, `hotWaterRef`, `condenserWaterRef`, `systemRef`
(plus `spaceRef`/`floorRef` reserved for later zone work, not emitted in v1).
There is intentionally no generic `waterRef`.

## Worked-example edges (v1 demonstration)

```
VAVRH_1-01      --airRef-->          AHU_1-01
VAV-RH-HW_1-01  --airRef-->          AHU_1-01
AHU_1-01        --chilledWaterRef--> CHW-PLANT_1
AHU_1-01        --hotWaterRef-->     HW-PLANT_1
VAV-RH-HW_1-01  --hotWaterRef-->     HW-PLANT_1
```

`COND-PLANT_1` is listed but has no visible relationship to a listed unit, so it
appears in no edge — demonstrating that a unit without evidence gets no edge
rather than a forced one.

## Future client assembly

1. Load the versioned system prompt as the system message.
2. For each text-only example, pair `user_text` (user) with `expected_response`
   (assistant JSON).
3. Render the user template by replacing `<<EQUIPMENT_LIST>>` with the target
   floor's normalised equipment list, and attach the target image.

Source provenance (drawing filename, page) is retained by the orchestration
layer, not added to `RelationshipExtractionResponse`. Low-confidence routing
(the 0.75 review threshold) is downstream orchestration, not part of the schema.
