You are reading one BMS (Building Management System) graphic page screenshot
from a Niagara-style workstation. Your job is to extract relationship EVIDENCE
only — transcribe what is visibly on the page. Do not infer, do not guess, and
do not use knowledge of other pages.

Report strict JSON with exactly this shape:

{
  "page_title": "<the equipment page title shown at top-center>",
  "linked_widgets": [
    {"label": "<equipment name on the linked widget box, e.g. 'AHU 02 A', 'OAVAV_02_04', 'DOAS_22_1'>",
     "points_shown": ["<point rows inside that widget>"],
     "values_live": true}
  ],
  "water_valves": {"chilled_water": false, "hot_water": false,
                   "detail": "<valve point names seen, e.g. CHW Vlv Cmd, WW Vlv Pos>"},
  "nav_tree_visible": false,
  "nav_tree_items": ["<entries if a navigation tree panel is open>"],
  "summary_table_rows": ["<entity names if an entity summary table is visible>"],
  "breadcrumb": "<breadcrumb path if visible, else empty>"
}

Definitions and rules:

1. A "linked widget" is a small titled box naming ANOTHER piece of equipment and
   showing one or more of its points (e.g. a VAV page carrying an 'AHU 02 A' box
   with DA Temp / DA Flow). The main unit's own point callouts (labels pointing
   at its 3-D graphic) are NOT linked widgets.
2. `values_live` is false when the widget's values are dashes (--). The link is
   still real BMS configuration either way — report it.
3. The page title is authoritative. Read it carefully character by character;
   do not normalize or "fix" it.
4. Water valves: CHW / CHWR / CHWS points mean CHILLED water. WW / WWR / WWS
   points mean WARM (HOT) water — set hot_water=true for them.
5. Navigation trees and entity summary tables are INVENTORY evidence: list their
   entries verbatim, but never convert them into linked widgets — co-appearing
   in a menu or summary list is not a serving relationship.
6. If this is a FLOOR OVERVIEW page (many unit chips placed on a floor plan, no
   single equipment graphic), set page_title to the floor name, leave
   linked_widgets empty, and list the unit chips in summary_table_rows.
7. Return JSON only — no prose, no markdown fences.
