Inspect the complete attached image and extract every distinct, clearly visible,
in-scope HVAC equipment identifier.

Do not limit extraction to the page title. Include clearly visible contextual,
upstream, or neighboring labels when they name concrete in-scope equipment units.

Exclude point-level and non-equipment labels only from the equipment candidate
list. Points, commands, sensors, statuses, setpoints, measurements, alarms,
rooms, zones, and generic components must not become equipment candidates. The
original full image and its other visible evidence are preserved for later
pipeline stages.

Generic components means labels such as fan, filter, damper, or coil when they
do not identify a distinct in-scope equipment unit.

Retain complete identifiers in raw_label and canonical_name. Return
EquipmentExtractionResponse JSON only.
