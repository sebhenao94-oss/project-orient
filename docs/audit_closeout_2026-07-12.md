# W1-W6 Audit Closeout — 2026-07-12

## Verdict

The `w7/audit-fixes` branch closes Claude's F1-F5 findings and the additional
offline defects found while tracing the actual user paths. It is a strong
**Floor 02 closeout candidate**, not evidence that live services or every floor
have been accepted. No AWS write, paid-model request, production-database
mutation, video recording, or GitHub push was performed during this audit.

The live `origin/main` baseline was verified as `d643709`; the local branch was
created from that same commit. Sensitive source material and credentials remain
outside Git.

## Scope reconciliation

Where the supplied sources differ, this closeout applies the later supervisor
direction first, then the detailed W1-W6 schedule, then the original project
brief. Claude's audit is treated as an implementation-quality plan, not a new
scope authority.

- No distinct W0 deliverable was present in the supplied brief or pasted W1-W6
  schedule. This report therefore makes no unsupported W0 completion claim.
- Point classification was explicitly removed from the final project scope.
- Zone orientation was formally descoped together with point classification
  (confirmed by the team member relaying the lead's final-two-weeks direction:
  both were the original W7 scope and neither continues). The review UI
  identifies the tab as a placeholder rather than presenting it as completed.
- Later direction asks for per-floor outputs, but the supplied evidence and
  committed run artifacts cover Floor 02. The repository has per-floor input
  and output paths; other-floor source runs have not been represented as done.
- The canonical artifact uses `in_topics`, while the original brief-mandated
  discrepancy artifact retains `in_points`. They describe different artifact
  contracts and are intentionally not renamed into one another.
- The original brief/database example uses names such as `AHU_2-01`; later
  feedback gives `AHU_2_01`. The branch preserves the current dash form until
  the owner selects one convention.

## Implemented findings

| Finding | Closed behavior |
|---|---|
| F1 — routing was dead on the CLI path | Large drawings route before extraction to the configured capable model and overlapping full-resolution tiles; screenshots stay on the lower-cost path. Hybrid batch behavior is explicit. Checkpoints fingerprint model, route, source, prompt content, examples, and tiling settings. Partial tile failures now keep a drawing incomplete instead of checkpointing a partial success. |
| F2 — LLM topics output could not flow downstream | Normalization accepts deterministic and LLM schemas, preserves upstream flags/reasons, and refuses incomplete input coverage. Vision escalation clears only evidence it actually resolves. |
| F3 — relationship refs/reasons were lost | Specific Haystack ref columns are joined through robust raw/canonical lookup; conflicts remain review-flagged; edge reasons reach the API and UI. |
| F4 — committed artifacts contradicted code | W04/W06 derived CSVs were deterministically regenerated without changing the 56-unit canonical-name set. W03 raw evidence was not edited. |
| F5 — docs and metrics were stale | Prompt/download/run docs now match the runnable state; OpenAI-compatible token fields are counted; the simplified type context is used by topics vision escalation. |

Additional closeout hardening:

- Stage 1 now hands Stage 2 an atomic manifest retaining original PDF name,
  page, SHA-256, and image eligibility.
- Eligible images that fail, disappear, or yield an unexplained empty result
  make the run incomplete and nonzero by default; partial pilots require an
  explicit override.
- Reviewer correction data is allowlisted and consumed by the next extraction
  prompt; its content invalidates stale checkpoints.
- Every non-floor-ambiguous equipment row is actionable. Discrepancy actions
  resolve the same equipment item rather than inflating totals. Engineer-drawn
  relationship proposals have typed, validated, durable source data; clear and
  commit operations use server-authoritative counts and surface errors. Applied
  items are excluded from later sessions for the same property/floor.
- Relationship reads are scoped by property/floor; a session for a different
  property cannot approve the Floor-02 W6 relationship inbox.
- Python dependencies are locked for Python 3.8 and CI runs the offline Python
  suite plus Node 22 `npm ci`, lint, and production build with read-only GitHub
  permissions.

## Offline acceptance evidence

- Python 3.8: **617 tests passed** (`py -m unittest discover tests`).
- Frontend: `npm run lint` completed with no warnings; `npm run build` passed.
- W06 canonical/discrepancy artifacts: **56 rows each**.
- W06 relationship evidence: **44 candidate edges**, **12 accepted topology edges**, **3 aggregated unresolved endpoints**, **38 orphans**, and **43 populated ref cells** across **24 canonical rows**, with the conflicting edge preserved for review.
- Canonical header includes `source_files`, `airRef`, `chilledWaterRef`,
  `hotWaterRef`, `condenserWaterRef`, and `spaceRef`; 30 drawing-backed rows
  carry source-file provenance.
- Initial Floor-02 review inbox: **93 unique decisions** (49 equipment plus 44
  relationships); discrepancies are evidence views, not duplicate decisions.

## Authorization and external acceptance gates

These actions were deliberately not inferred from the request:

1. Select canonical naming: keep `{Type}_{floor}-{unit}` (current brief/DB
   form) or migrate to `{Type}_{floor}_{unit}` (later feedback example).
2. Select folder naming: `Floor_2` or `Floor_02`. This decision should precede
   default per-floor output paths and additional-floor execution.
3. Decide whether to add post-deduplication counts alongside raw extraction
   metrics, and whether to deprecate the superseded `pipeline.relationships`
   CLI. Neither was changed by default.
4. ~~Confirm the zone-orientation disposition.~~ Resolved 2026-07-12:
   descoped with point classification per the lead's direction.
5. Approve any live S3/model run. Credentials and potentially paid inference
   are required; source completeness must then be evaluated from the emitted
   run artifacts.
6. Select and integrate authentication/authorization before any network-exposed
   review API deployment. The current API is appropriate for local/internal
   offline acceptance, not public production exposure.
7. Native Anthropic batch IDs are not yet persisted for mid-poll resume; decide
   whether to fund that provider-state ledger or run realtime when interruption
   recovery matters more than batch discount.
8. Obtain the documented database-admin grant, then approve live review-table
   setup and a real review-to-production session.
9. Record the walkthrough video using the prepared script.
10. Review this local branch before authorizing a push to GitHub.

## Known boundary

The stages have explicit manifests and documented commands, but there is no
single command that orchestrates ingestion through production commit. That is
optional post-project integration work and is not represented as completed.
Engineer-drawn relationship proposals are persisted after their first review
action, but the UI does not yet reload uncommitted posted proposals after a page
refresh because there is no session-actions read endpoint.

