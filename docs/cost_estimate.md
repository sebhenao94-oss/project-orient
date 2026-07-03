# Inference cost estimate (per floor / per site)

Requested by Sourav alongside the Claude key provisioning: a rough cost
calculation for our expected workload against the escalation pipeline, based on
trial runs. Figures marked **measured** come from actual spend; figures marked
**projected** are extrapolations and should be replaced with `write_cost_log`
output (`pipeline/cost.py`) as more live runs accumulate.

## Measured so far

- **Total spend to date: ~$0.35** against the $20/month team cap. That covered
  all W3–W6 live Claude work on Floor 2: several extraction passes over the 22
  BMS screenshots, LLM-assisted topics parsing over 456 topic rows (37
  contexts), vision second passes on flagged units, and tiled relationship runs
  over the full-resolution Floor_2A mechanical drawing (~24 tiles per sheet at
  2500 px).
- Price table used (USD per 1M tokens, from `pipeline/cost.py`): Haiku 1/5,
  Sonnet 3/15, Opus 5/25 (input/output). Batch API halves these; a cached
  system/few-shot prefix bills repeat reads at 0.1x.

## What drives cost

The escalation ladder (free Qwen L1 → Haiku → Sonnet → Opus) keeps most
screenshots on free or Haiku tiers. The dominant cost is **mechanical drawings**,
which route straight to the top tier and fan out into ~24 full-resolution tiles
per sheet. Topics parsing is text-only Haiku and is close to free at this
volume.

## Projection (per single full pass)

| Workload | Assumptions | Real-time | Batch API |
|---|---|---|---|
| One floor (Floor 2 shape: 22 screenshots, 456 topics, 1 drawing sheet) | most screenshots ≤ Haiku, drawing tiles on Opus, cached prompt prefix | ~$0.10–0.20 | ~$0.05–0.10 |
| Whole building (5 floors) | same mix per floor | ~$0.50–1.00 | ~$0.25–0.50 |
| W7 point classification (per floor) | ~456 points, Haiku, essential-tag list + few-shots in a cached prefix | < $0.10 | < $0.05 |

The projection is anchored to the measured $0.35, which bought several
experimental passes of one floor — so a single clean pass costs a fraction of
that. As a cross-check, the project brief's own estimate for a ~50-equipment /
~200-point site was $0.80–1.50 in batch mode on a Sonnet-class model; our
figures land below that because the ladder keeps easy images off the paid tiers
entirely.

## Headroom

At these rates the $20/month cap supports roughly **20–40 full building passes
per month** in batch mode — far more than the weekly dev cadence plus the W7/W8
held-out runs require. The realistic risk to the budget is not routine runs but
repeated full-resolution drawing experiments on Opus; those should default to
the Batch API (50% off) and reuse cached prefixes.

## Keeping this honest

Each live stage writes a JSON cost summary via `pipeline/cost.py::write_cost_log`
(tokens in/out, cache reads/writes, estimated USD, per model). As W7–W8 runs
land, replace the projected column above with the measured aggregates from those
logs — the W8 performance analysis needs the measured figures, not these
estimates.
