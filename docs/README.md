# Documentation

Project notes, schema references, and milestone documentation.

- [`HISTORY.md`](HISTORY.md) — chronological W2–W3 build record (Stage 1
  progress, Colab/Qwen smoke tests, live validation results, pilot failure
  modes, original supervisor question list). Moved out of the front-page README.
- [`cost_estimate.md`](cost_estimate.md) — measured spend to date and projected
  per-floor / per-site inference cost against the $20/month cap.
- [`w5_database_admin_request.md`](w5_database_admin_request.md) — pending ops
  request: create the review tables (`review_session`, `review_action`,
  `correction_log`) in `bas_data`.
- [`w5_equipment_details_schema.md`](w5_equipment_details_schema.md) — the
  verified `equipment_details` write-path schema (post `floorRef` / `systemRef`
  renames).
- [`equipment_extraction_qwen_pilot.md`](equipment_extraction_qwen_pilot.md),
  [`inference_smoke_test.md`](inference_smoke_test.md) — W3-era pilot notes.
