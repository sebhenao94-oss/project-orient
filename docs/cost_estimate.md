# Inference cost estimate (per floor / per site)

Requested by Sourav alongside the Claude key provisioning: a rough cost
calculation for our expected workload against the extraction routing paths, based on
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

The documented extraction CLI uses an explicit two-tier route: screenshots use
the configured lower-cost `--model`, while large mechanical drawings use
`--drawing-model` and fan out into ~24 full-resolution tiles per sheet. The
free-Qwen → Haiku → Sonnet → Opus ladder remains available as experimental
library code; it is not the default CLI path. Topics parsing is text-only Haiku
and is close to free at this volume.

## Projection (per single full pass)

| Workload | Assumptions | All realtime | Hybrid `--batch` |
|---|---|---|---|
| One floor (Floor 2 shape: 22 screenshots, 456 topics, 1 drawing sheet) | screenshots on the lower-cost model, drawing tiles on Opus, cached prompt prefix | ~$0.10–0.20 | Measure from run metrics; only screenshots receive the batch discount |
| Whole building (5 floors) | same mix per floor | ~$0.50–1.00 | Measure from run metrics; drawing tiles remain realtime |

The projection is anchored to the measured $0.35, which bought several
experimental passes of one floor — so a single clean pass costs a fraction of
that. As a cross-check, the project brief's own estimate for a ~50-equipment /
~200-point site was $0.80–1.50 in batch mode on a Sonnet-class model; our
figures land below that because screenshots use the lower-cost configured model
and the prompt prefix is reused.

## Headroom

Do not derive monthly headroom from the hybrid column until a complete routed
run has written measured per-model metrics. The realistic budget risk is
repeated full-resolution drawing experimentation on Opus: drawing tiles run
realtime even when `--batch` is selected, so checkpoints and cached prefixes are
the primary safeguards against repeat spend.

## Keeping this honest

Each live stage writes JSON usage data through `pipeline/cost.py` (tokens in/out,
cache reads/writes, estimated USD, per model). Replace the hybrid placeholders
above with the end-to-end `run_metrics.json` aggregates from a complete routed
run; the batch-only cost log does not include realtime drawing tiles.
