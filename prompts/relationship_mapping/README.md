# Relationship Mapping Prompts

Versioned prompt artifacts for inferring equipment-to-equipment relationships
from BMS graphics and mechanical drawings, expressed as Haystack reference edges.

## Files

- `v1_system.md`: role, ref vocabulary, evidence and conflict rules, JSON-only
  output contract.
- `v1_user_template.md`: reusable target user message. Contains the
  `<<EQUIPMENT_LIST>>` placeholder, into which the orchestration layer injects
  the normalised equipment list for the target image.
- `v1_few_shot_examples.json`: text-only few-shot manifest.

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
