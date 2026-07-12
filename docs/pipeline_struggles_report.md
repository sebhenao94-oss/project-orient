# Pipeline Struggles & How the Team Solved Them

_Closeout edition · 2026-07-12 · Team 4 · "Failure modes" and "Lessons
learned" record for the W1-W6 delivery._

This report collects the significant problems the ORIENT pipeline hit between
W2 and W7, what each one cost us, how it was solved, and what we would do
differently. Written for a technical reader who has not seen the project;
evidence for every episode is committed in the repo (snapshots under
`data/snapshots/`, the chronological record in `docs/HISTORY.md`, and the
findings docs referenced below).

---

## 1. Infrastructure: no inference environment, ephemeral workarounds

**Struggle.** The brief assumed a team GPU for an open-weights vision model,
but no GPU environment was ever provisioned. Early development ran
Qwen3-VL-2B on a free Google Colab T4 behind a quick-tunnel — ephemeral URLs,
session resets, a 5-requests-then-429 rate limit, and GPU memory pressure
(five full-resolution few-shot images plus a target exceeded the T4, forcing a
768 px resize inside the endpoint).

**Fix.** We kept the provider-neutral OpenAI-compatible client seam and added
an explicit two-tier user path: screenshots use the configured lower-cost
model, while large drawings route before extraction to the configured capable
model and full-resolution tiling. The L1-L4 cheapest-first escalation ladder
(free Qwen when available → Haiku → Sonnet → Opus) remains an experimental
library path, not the documented CLI default. Historical development spend was
~$0.35 against a $20/month cap. The seam meant the provider could change
without rewriting extraction or parsing.

**Takeaway.** Building against a provider-neutral seam from day one was the
single best architectural decision of the project: the inference backend
changed twice without touching the pipeline.

## 2. Extraction accuracy: the model tells you things that aren't there

Three distinct failure modes surfaced in the first live pilots (June 10–11):

- **Point labels emitted as equipment.** `DA Temp`, `Fan Cmd`, `Zone Temp Sp`
  came back as equipment candidates. *Fix:* a mechanical candidate gate in the
  prompt — a candidate must begin with a supported equipment prefix and carry a
  unit identifier.
- **Few-shot label leakage.** The model copied `VAVRH_2_1` from a
  demonstration image into results for ~5 pages where it is not visible.
  *Fix:* explicit "demonstrations only; every identifier needs direct visual
  evidence in the final target image" prompt language; leakage went to zero in
  the v3 independent pilot.
- **Silent truncation.** Dense pages exceeded the endpoint's 512-token
  completion default and the JSON came back cut off. *Fix:* the client sends
  `LLM_MAX_COMPLETION_TOKENS` (default 2048) on every request; the strict
  parser rejects rather than repairs malformed output, so truncation is
  visible, not silent.

The v2→v3 prompt iteration turned an independent pilot from **2 leaked labels
and 3 of ~24 identifiers** into **21 correct identifiers with zero leakage and
zero hallucinations**.

**Takeaway.** Strict schema validation that *preserves* bad output was worth
more than any single prompt improvement — every failure mode above was caught
because malformed responses were kept as evidence instead of silently cleaned.

## 3. Resolution: the pipeline quietly loses what it can't see

**Struggle.** Two opposite problems. (a) The ingestion quality gate's 750 px
short-side minimum silently skipped 11 of the 22 real BMS screenshots
(715–747 px tall). (b) Full-resolution mechanical drawings (12600×9000 at
300 DPI) were downsampled by the endpoint to unreadability — the model
correctly returned `{"equipment":[]}` rather than hallucinating, but that
meant **drawings contributed nothing**.

**Fix.** (a) Environment-configurable thresholds; the batch ran at 700.
(b) **Tiling**: split drawings into overlapping full-resolution tiles, run
each non-blank tile (a cheap ink-fraction pre-filter skips empty floor area),
and union the results with whitespace-insensitive dedup across tile overlaps.

**Takeaway (the lead's point, confirmed empirically).** Per-item confidence
cannot catch omissions — items the model never saw don't appear as
low-confidence, they just don't appear. The fix is routing by input class at
ingestion (drawings → the top-tier model through the tiling path), not
threshold calibration.

## 4. Relationships: the floor plans don't contain the answer

**Struggle.** W4's relationship extraction from mechanical floor plans, even
tiled at full resolution on the top-tier model, recovered **1 conflicted edge**
for the whole floor. Weeks of prompt iteration could not fix this, because the
serving topology largely isn't drawn on the plans.

**Fix.** Look where the information actually lives: the BMS graphic pages
embed the topology as **linked equipment widgets** (a terminal's page names its
serving AHU, with live values to cross-check). One vision pass over the same
22 screenshots took the edge set from 1 conflicted edge to **44 edges**
(airRef, chilledWaterRef, hotWaterRef) with provenance and evidence-based
confidence, revealing the two-level chain (AHU→VAV/FPTU primary air;
DOAS→OAVAV→FCU ventilation air; valve evidence for plant refs). See
`docs/relationship_graphics_findings.md`.

**Takeaway.** When extraction accuracy plateaus, question the *source*, not
just the prompt. The cheapest fix was a different input, not a better model.

## 5. Topics parsing: deterministic rules break on naming reality

**Struggle.** The original topics→equipment exporter assumed a fixed
`<floor>/<equipment>/<point>` path shape. It worked for Floor 02 but breaks on
buildings with different segment orders, separators, or prefixes — and can
silently miss equipment or merge/split units (per the supervisor's review).

**Fix.** Inverted the roles: an **LLM-assisted parser is the primary path**
(no fixed-shape assumption; groups points into units with per-unit
`review_required`/`review_reason`), and the deterministic parse is kept only
as a validation cross-check that flags disagreements. Units the text parser
flags get a **vision second pass** on their source screenshot — agreement
clears the flag ("CONFIRMED"), disagreement records the conflict — before
falling back to human review.

**Takeaway.** Deterministic rules are excellent validators and terrible
primaries in messy naming domains.

## 6. Reconciliation: the same unit spelled five ways, and units on the wrong floor

**Struggle.** No equipment list was provided — equipment had to be inferred
from point names and drawings independently, then reconciled. The same unit
appeared as `AHU-02A`, `AHU_02A`, and `AHU 02 A`; numeric padding varied
(`OAVAV_2_01` vs `OAVAV_02_01`); and seven ventilation contexts carried
contradictory floor evidence (path said one floor, name token said another).
One drawing label (`DAWNV_2_09`) was an OCR misread of `OAVAV_2_09`; two FCU
page headers were read from the wrong page element; model confidence was a
uniform, uncalibrated 0.99 — useless for ranking any of this.

**Fix.** A separator- and zero-padding-insensitive `canonical_key` for
matching; a `{Type}_{floor}-{unit}` canonical naming convention matching the
DB worked example; category-based gap analysis (`matched` / `topics_only` /
`drawing_only` / `type_mismatch`) with **floor-ambiguous units carried as an
explicit status routed to review** rather than silently assigned; misreads
preserved in the snapshots as review-flagged rows rather than cleaned away.
Within-image duplicate suppression was added as a deterministic belt-and-braces
pass after the prompt-level fix proved incomplete (`FCU_02_5`).

**Takeaway.** Never clean data at extraction time: every known defect that was
*preserved and flagged* became reviewable evidence; anything silently fixed
would have been an invisible error.

## 7. Cost & reliability: paying for the same tokens twice

**Struggle.** (a) Prompt caching appeared to work but wasn't: the system block
alone sat below Haiku's 2048-token cache minimum, so the large few-shot images
— the bulk of every request — were re-sent at full price on every call.
(b) A crashed or interrupted batch reprocessed every image from scratch.
(c) Token spend was only visible for the batch path, opt-in.

**Fix.** (a) Move the cache breakpoint to the end of the few-shot prefix, so
the whole demonstration block caches at ~0.1×. (b) **Run checkpointing**: an
append-only ledger keyed by `(image sha, page, prompt version, model)` records
every completed image as it lands; restarts reuse succeeded results and re-send
only incomplete or failed ones, and changing the prompt or model automatically
invalidates old entries. (c) **End-to-end metrics**: every LLM call site
records usage into a run-scoped recorder; each run emits `run_metrics.json`
with tokens and estimated cost per model, totals, wall time, and raw confident
vs. review-flagged counts. The Message Batches API (~50% price) is opt-in;
hybrid mode batches screenshots while tiled drawings remain realtime.

**Takeaway.** Cost control is an architecture property, not a discipline
property — caching, checkpointing, batching, and metrics each had to be built
once, in the right seam, to apply everywhere.

## 8. Database: two false starts and one still-pending grant

**Struggle.** (a) An early audit concluded the team needed `GRANT USAGE` on
`equipment_details_equipment_id_seq` before any equipment write — a
misdiagnosis that stalled write-path planning for a week. (b) The W5 review
tables (`review_session`, `review_action`, `correction_log`) require `CREATE`
on schema `public`, which the team role does not have.

**Fix / status.** (a) Read-only verification showed `equipment_id` is
`GENERATED BY DEFAULT AS IDENTITY` — no sequence grant needed, and
`orient_team_4` already holds INSERT/UPDATE on `equipment_details`. (b) The
DDL and grant script have been ready since W5
(`docs/w5_database_admin_request.md`); a live check on 2026-07-10 (tunnel up,
credentials verified, `has_schema_privilege('public','CREATE') = false`)
confirmed the admin has not yet applied it. `scripts/upload_reviewed.py check`
now diagnoses this state in one command. Live table creation and a real
review-session commit therefore remain external acceptance steps; the commit
transaction is covered offline against scripted fakes.

**Takeaway.** Verify privileges by querying the catalog, not by reasoning from
error messages — both DB false starts came from trusting an interpretation
over `has_table_privilege` / `has_schema_privilege`.

## 9. Team & repo workflow

**Struggle.** Two build tracks and two machines produced diverging branches
(`dev_sd_2` re-implemented escalation that had already landed on main), stale
local checkouts (the Desktop clone fell 37 commits behind), prompt files
proliferating as `v1/v2/v3` copies, and source files scattered in
machine-specific folders that made README commands non-reproducible.

**Fix.** Single current-best prompt set with git history as the version record;
`downloads/<floor>/` as the standard input location with an S3 sync script
(`populate_downloads.py --from-s3 --check` detects newly uploaded bucket
files); per-floor `outputs/<floor>/`; supervisor review items tracked as
numbered fixes in commit messages.

**Takeaway.** Repo hygiene items feel cosmetic until a reviewer, a second
machine, or a teammate's branch is involved — then each one is a real defect.

---

## What we would do differently from the start

1. **Provider-neutral seams everywhere** — they paid for themselves twice
   (inference pivot, review-store fake/postgres swap). Keep.
2. **Question the evidence source before iterating prompts** — the
   relationships pivot (§4) recovered 44× more signal than any prompt change.
3. **Treat omissions, not just errors, as the accuracy risk** — route by input
   class at ingestion; confidence thresholds cannot see what was never
   extracted.
4. **Preserve every defect as flagged evidence** — the review board's value
   comes from the pipeline's honesty about what it isn't sure of.
5. **Ask for infrastructure (GPU, DB grants) in week one** — every external
   dependency that wasn't pre-provisioned became the long pole of its phase.
6. **Meter from day one** — metrics added in W7 should have existed in W3; the
   early Qwen runs left no usage record for the final report's comparison.
