# Relationships from BMS graphics — findings & method

_2026-07-02 · Floor 02, property `msa_orient_building_1` ("Coda") · supersedes the
plan-geometry-only approach documented in the 2026-06-30 finding for Sourav._

## TL;DR

**The BMS graphic pages embed the serving topology as linked equipment widgets,
and reading them recovers the relationship graph the mechanical floor plans
couldn't.** One vision pass over the 22 existing Floor-2 screenshots took the
candidate edge set from **1 conflicted edge** (the W6 tiling result) to **44
edges** — airRef, chilledWaterRef, and hotWaterRef — each carrying provenance and
a source-based confidence score. The serving pattern is a two-level chain:

```
AHU 02 A ──airRef──> VAV_2-01, VAV_2-05, FPTU_2-01..05            (primary air)
DOAS_22_1 ──airRef──> OAVAV_2-01..10 ──airRef──> FCU_2-01..05     (ventilation air)
AHU 02 A ──> CHW-PLANT_1 + HW-PLANT_1;  AHU 02 C ──> CHW only
FCUs ──> CHW + HW plants;  FPTUs ──> HW plant                      (valve evidence)
```

## Method (now in the pipeline)

1. **Vision transcription** — each screenshot goes through the
   `prompts/relationship_graphics` package: the model transcribes the page title,
   linked equipment widgets (label, points, live-vs-dashed), water-valve points,
   and any nav-tree/summary inventory. It infers nothing.
2. **Deterministic fusion** — `pipeline/graphics_relationships.py` turns evidence
   rows into edges with a source-based confidence rubric (0.95 live-synced link /
   0.85 offline link / 0.55 pattern extrapolation / valve+single-plant 0.90–0.85),
   merges drawing-tiling edges as an independent corroborating source, and routes
   anything <0.75, conflicted, or vocabulary-flagged to review.
3. Canonical names come from `normalization.canonical_key` +
   `equipment_vocab.canonical_name`, so edges land on the current
   `{Type}_{floor}-{unit}` zero-padded vocabulary (`AHU_2-A`, `FCU_2-03`).

Regenerate the committed snapshot offline:

```powershell
py -m pipeline.graphics_relationships `
  --from-evidence-csv data\snapshots\w06\relationship_evidence_floor_02.csv `
  --tiling-json data\snapshots\w06\relationships_tiling_floor_02.json `
  --output-json data\snapshots\w06\relationships_floor_02.json
```

Live extraction (needs `ANTHROPIC_API_KEY`): `--screenshots-dir downloads\Floor_2
--run-live --evidence-csv-out ...`.

## Validation record

Dual pass on 2026-07-02: an in-session Claude read and an API run
(`claude-sonnet-4-6`, 42.0k in / 5.8k out tokens ≈ **$0.21**) agreed on **14/14
serving links**, and the API pass independently confirmed the valve evidence on
every FCU and FPTU page. Divergences, both routed to review:

- one page-title character misread (`OAVAV_02_01` → `QAVAV_02_01`) — caught by
  canonical-key normalization as an unrecognized type;
- one mis-attributed CHW valve on `VAVRH_2_1` (a reheat VAV has no chilled-water
  coil; excluded from the committed evidence with a note).

## Key discoveries

1. **Linked widgets are the serving hierarchy.** DA Temp/DA Flow values on the
   terminal pages sync live with AHU 02 A's own page (54.5 °F / 2444.1 cfm seen on
   four pages simultaneously) — the links are deliberate BMS configuration.
2. **The DOAS the W3 validator rejected as out-of-scope is real.** `DOAS_22_1` is
   the OA parent of the whole OAVAV→FCU ventilation chain. It and the two plants
   are emitted as `equipment_candidates` in the snapshot. The graph validator
   aggregates their 31 edge occurrences into three unresolved-endpoint errors
   and three explicit review findings; they remain blockers until a reviewer
   approves the candidates into canonical equipment (Appendix A's
   plant-flagging flow).
3. **Controller trunks do NOT track air systems** (negative result worth keeping):
   `VAV_2_01` sits on the underscore-vintage DEV362xx trunk alongside
   `AHU_2_01..03`, yet its own page names dash-vintage `AHU 02 A` as its source.
   Device ranges are wiring/vendor history, not airflow.
4. **Floor-ambiguity evidence** (open Core question #4): the Floor-1 overview page
   displays `OAVAV_01_1..7` / `EVAV_01_1` / `EVAV_01_4` — matching the seven
   contested `_1_` topics contexts one-for-one. They are physically Floor-1 units
   whose topics are filed under the `Floor_02` path.
5. **AHU heating differs per unit** — AHU 02 A has CHW + WW (hot-water) valves,
   AHU 02 C has CHW only — so water refs are per-unit, never per-type.
6. `ref_type_sanity` now accepts **OAVAV as an air parent** (each FCU graphic
   carries its upstream OAVAV widget); a plain VAV still cannot be one.

## What's still unknown (and the cheapest way to close each)

| Unknown | Cheapest evidence |
|---|---|
| Which terminals do AHU_2-01/02/03 and AHU 02 B serve? | capture their pages + VAV_2_02..07 pages |
| VAVRH_2_1..5 parent + reheat type (`Heat1` = elec or HW?) | capture VAVRH_2_2..5 pages; check topics for HwValve points |
| FCU_02_6/8/9 OA source (no OAVAV widget on graphic) | capture their pages / Points tab |
| Plant membership (chillers, boilers, pumps) | capture the **"WW CHW System"** nav-tree pages |
| DOAS_22_1 details | capture its page (click the widget) |
| EAVAV (exhaust) parents | capture EVAV_02_1..3 pages |

**Screenshot shopping list for the next BMS session:** AHU 02 B, AHU_2_01..03,
VAV_2_02..07, VAVRH_2_2..5, EVAV_02_1..3, FCU_02_7, FPTU_2_06/07, DOAS_22_1,
TF_02_1, IDU_02_1, and every page under **WW CHW System**. That set likely closes
the airRef graph and opens the water-side graph.

## Committed artifacts (`data/snapshots/w06/`)

- `relationship_evidence_floor_02.csv` — verified vision-pass evidence (in-session
  primary + API-confirmed valve rows, disputed rows excluded with notes)
- `relationship_evidence_floor_02_api.csv` — the raw API verification pass
- `relationships_tiling_floor_02.json` — the single tiled-drawing candidate edge
  (recorded from the 2026-06-30 Opus run), merged as a corroborating source
- `relationships_floor_02.json` — **the fused 44-edge candidate snapshot** the
  review agent loads (16 edges routed to review; 4 non-edge review notes;
  3 equipment candidates)
- `canonical_equipment_floor_02.csv` / `discrepancy_report_floor_02.csv` — the W4
  artifacts regenerated onto the current zero-padded naming convention (the
  immutable `w04/` copies predate the W4-review naming fix)
- `graph_validation_floor_02.json` — validator report over the current edges:
  44 candidates, 12 accepted into topology, 3 aggregated unresolved endpoints,
  38 canonical terminal orphans, and 19 review items (`passed=false` is the
  honest pre-review state)
