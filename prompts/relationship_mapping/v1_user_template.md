Infer the equipment-to-equipment relationships visible in the attached image,
using only the equipment in this list:

<<EQUIPMENT_LIST>>

Return RelationshipExtractionResponse JSON only.

Every edge's child and parent must appear verbatim in the list above and have
direct visual evidence in this image. Use airRef for terminal-to-air-handler air
service, and chilledWaterRef / hotWaterRef / condenserWaterRef for
equipment-to-plant water service. Use systemRef only when a clear serving
relationship has no specific reference type.

One airRef parent maximum per terminal unit. When the serving parent is
ambiguous, emit your single best estimate with conflict set to true and a short
conflict_reason rather than emitting two parents or guessing silently.

A unit with no visible relationship gets no edge. If no relationships are
visible in this image, return {"relationships":[]}. Do not copy equipment names
from the demonstration examples.
