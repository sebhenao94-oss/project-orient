# Documentation

Project notes, schema references, and milestone documentation.

- [`HISTORY.md`](HISTORY.md) — chronological W2–W7 build record (Stage 1
  progress, Colab/Qwen smoke tests, live validation results, pilot failure
  modes, original supervisor question list). Moved out of the front-page README.
- [`cost_estimate.md`](cost_estimate.md) — measured spend to date and projected
  per-floor / per-site inference cost against the $20/month cap.
- [`relationship_graphics_findings.md`](relationship_graphics_findings.md) — how
  the BMS linked-widget vision pass recovered 44 candidate relationship edges
  (vs 1 from drawing tiling), the dual-pass validation record, and the
  screenshot shopping list for closing the remaining unknowns.
- [`pipeline_struggles_report.md`](pipeline_struggles_report.md) — the
  team-lead-requested report on pipeline struggles and how they were solved
  closeout report (failure modes, solutions, and lessons learned).
- [`review_walkthrough.md`](review_walkthrough.md) — human review board
  walkthrough: how to read flags/reasons, approve/edit/reject, commit, the
  upload script, the live-DB cutover runbook, and the recording script for the
  walkthrough video.
- [`audit_closeout_2026-07-12.md`](audit_closeout_2026-07-12.md) — reconciled
  W1-W6 scope, audit-fix evidence, external acceptance boundaries, and owner
  decisions still required.
- [`w5_database_admin_request.md`](w5_database_admin_request.md) — pending ops
  request: create the review tables (`review_session`, `review_action`,
  `correction_log`) in `bas_data`.
- [`w5_equipment_details_schema.md`](w5_equipment_details_schema.md) — the
  verified `equipment_details` write-path schema (post `floorRef` / `systemRef`
  renames).
- [`equipment_extraction_qwen_pilot.md`](equipment_extraction_qwen_pilot.md),
  [`inference_smoke_test.md`](inference_smoke_test.md) — W3-era pilot notes.
