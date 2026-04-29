# Strategy Battle Arena V2

Layer: research / strategy optimization arena.

Purpose: compare market-only strategy variants before they are allowed into the paper-candidate pipeline.

## Boundary

Allowed:

- read replay/evaluation data
- compare strategy parameter variants
- compare multiple forward-return horizons
- report global and per-symbol preferences
- classify variants as `REJECTED`, `WATCH`, or `PROMOTION_CANDIDATE`

Forbidden:

- account balances
- positions
- open orders
- decision gate writes
- execution intent writes
- execution plan writes
- broker/order actions

## State meaning

`PROMOTION_CANDIDATE` means the variant has performed well enough in research to deserve formal paper-candidate staging.

It does not mean live-ready.

Flow:

```text
RESEARCH_RESULT
  -> OPTIMIZATION_WINNER
  -> PROMOTION_CANDIDATE
  -> PAPER_CANDIDATE
  -> PAPER_PROVEN
  -> LIVE_ELIGIBLE
  -> LIVE_ENABLED

