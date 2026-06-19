Infer the equipment-to-equipment relationships that are visibly documented in
the attached image, using only the equipment in this list:

<<EQUIPMENT_LIST>>

Return RelationshipExtractionResponse JSON only, compact and on a single line.

Emit an edge only when the page's main graphic, a drawn duct/pipe/airflow path,
or an explicit schedule shows the parent serving the child. A side or left-hand
navigation panel, equipment tree, or menu that simply lists units is NOT
evidence of a serving relationship — do not connect units just because they are
listed together or one appears under another in such a tree.

Every edge's child and parent must appear verbatim in the list above. Use airRef
for terminal-to-air-handler air service, and chilledWaterRef / hotWaterRef /
condenserWaterRef for equipment-to-plant water service. One airRef parent
maximum per terminal unit; when the serving parent is ambiguous, emit your
single best estimate with conflict set to true and a short conflict_reason.

Prefer few high-evidence edges, or none, over many speculative ones. If this
page shows one unit's graphic plus a navigation list but no drawn or scheduled
serving connection, return {"relationships":[]}. Do not copy equipment names
from the demonstration examples.
