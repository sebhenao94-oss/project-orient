Inspect the complete attached image and extract every distinct, clearly visible,
in-scope HVAC equipment identifier.

This attached image is the final target image. Extract only identifiers visibly
present in this image. Do not copy identifiers from the few-shot demonstration
images or their expected responses.

Do not limit extraction to the page title. Include clearly visible contextual,
upstream, or neighboring labels when they name concrete in-scope equipment units.
Navigation menus, equipment trees, and summary table rows are valid sources when
their text is readable.

Exclude point-level and non-equipment labels only from the equipment candidate
list. Points, commands, sensors, statuses, setpoints, measurements, alarms,
rooms, zones, and generic components must not become equipment candidates. The
original full image and its other visible evidence are preserved for later
pipeline stages.

Generic components means labels such as fan, filter, damper, or coil when they
do not identify a distinct in-scope equipment unit.

Only return concrete equipment labels beginning with AHU, VAVRH, VAV, FPTU,
OAVAV, or FCU. Do not return any other visible label as equipment.

For example, DA Fan Sp, DA Fan Cnd, DA Temp, DA Flow, commands, setpoints,
statuses, measurements, rooms, and zones must be excluded.

If no qualifying equipment label is visible, return {"equipment":[]}.

If an identifier cannot be read directly in this image, omit it. Identifiers
that appear only in the demonstrations must never be returned.

Retain complete identifiers in raw_label and canonical_name. Return
EquipmentExtractionResponse JSON only.
