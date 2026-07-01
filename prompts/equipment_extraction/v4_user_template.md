Inspect the complete attached image and extract every distinct, clearly visible,
in-scope HVAC equipment identifier that this image is about.

This attached image is the final target image. Extract only identifiers visibly
present in this image. Do not copy identifiers from the few-shot demonstration
images or their expected responses.

Extract only the focal/subject unit(s) of this image plus any concrete in-scope
unit directly drawn, labeled, or connected to the focal unit on the main graphic.
Do NOT extract units that appear only in a side navigation panel, an equipment
tree or menu, or a bottom summary/monitoring table (such as a "VAVs Summary"
grid). Those list other or off-floor equipment for navigation and are not part of
this image's equipment.

If this image is a cropped tile of a mechanical drawing, extract only equipment
whose full label is clearly legible inside the tile. Blank, grid-only, dimension,
or title-block tiles contain no equipment; return {"equipment":[]} for those.

Exclude point-level and non-equipment labels only from the equipment candidate
list. Points, commands, sensors, statuses, setpoints, measurements, alarms,
rooms, zones, and generic components must not become equipment candidates. The
original full image and its other visible evidence are preserved for later
pipeline stages.

Generic components means labels such as fan, filter, damper, or coil when they
do not identify a distinct in-scope equipment unit.

Only return concrete equipment labels beginning with AHU, VAVRH, VAV, FPTU,
OAVAV, or FCU, and only when a unit identifier follows the prefix. Never return a
bare prefix (such as AHU or OAVAV) with no unit number; if a label is clipped and
only the prefix is legible, omit it. Do not return any other visible label as
equipment.

For example, DA Fan Sp, DA Fan Cnd, DA Temp, DA Flow, commands, setpoints,
statuses, measurements, rooms, and zones must be excluded.

If no qualifying equipment label is visible, return {"equipment":[]}.

If an identifier cannot be read directly in this image, omit it. Identifiers
that appear only in the demonstrations must never be returned.

Retain complete identifiers in raw_label and canonical_name. Return
EquipmentExtractionResponse JSON only.
