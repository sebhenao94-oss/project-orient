Inspect the attached image and extract clearly visible in-scope HVAC equipment.
Return only valid EquipmentExtractionResponse JSON with this shape:

{"equipment": [{"raw_label": "...", "canonical_name": "...", "equipment_type": "<allowed_type>", "confidence": 0.0}]}

If no clearly labelled in-scope equipment is visible, return:

{"equipment": []}

Do not include Markdown fences, prose, reasoning, source paths, database fields,
relationship fields, point-classification fields, or review-status fields.
