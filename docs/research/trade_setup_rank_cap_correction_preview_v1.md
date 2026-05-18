# Trade Setup Rank Cap Correction Preview V1

## Status

Research-only diagnostic preview. No production setup-filter behavior changed.

Safety markers:

- broker_private_calls=0
- broker_writes=0
- order_submission=0
- live_orders=0
- decision_gate_changes=0
- execution_planner_changes=0
- executor_changes=0
- setup_filter_behavior_changes=0
- db_writes=0

## Purpose

The fail-reason diagnostic showed that the latest 4h paper advice set had no setup-filter PASS rows. Most rows failed because their selection state was not eligible, but HYPE failed with `RANK_OUTSIDE_SWEET_SPOT` even though it was ranked `1`.

This preview checks whether the current rank sweet spot logic is inverted relative to the original intent.

## Current Production Behavior

`trade_setup_filter_v1:1.1` currently requires:

- `selection_state = WATCHLIST`
- `priority_rank` between `4` and `10`
- BTC prior 24h inside the configured non-damaged / non-overheated band
- asset not in the candidate weak set

That means rank `1`, `2`, and `3` can fail setup solely because they are top ranked.

## Preview Variants

The runner compares four interpretations:

- `current_behavior`: existing production setup-filter result.
- `rank_1_10_setup_eligible`: rank `1..10` is eligible for setup validation.
- `top_rank_priority_warning`: rank `1..3` remains setup-eligible but receives `TOP_RANK_PRIORITY` and `CHASE_RISK_PREVIEW` notes.
- `actionable_cap_preview`: setup eligibility is evaluated separately, then `max_actionable_candidates` is applied as a downstream cap preview.

The preview does not change runtime state. It only reads latest paper advice and setup-filter observations.

## Run Findings

Command:

```bash
python -m src.research.run_trade_setup_rank_cap_correction_preview_v1 \
  --venue bitvavo \
  --interval 4h \
  --limit 80 \
  --max-actionable 3 \
  --output table
```

Observed latest timestamps:

- latest paper advice: `2026-05-18 05:32:46 UTC`
- latest trade setup filter: `2026-05-18 05:32:46 UTC`

Aggregate result:

| Metric | Count |
|---|---:|
| rows reviewed | 41 |
| current setup PASS | 0 |
| current setup FAIL | 40 |
| corrected setup PASS preview | 1 |
| corrected setup FAIL preview | 40 |
| current actionable preview | 0 |
| capped actionable preview | 1 |

Current fail reasons:

- `SELECTION_STATE_NOT_ELIGIBLE`: 39
- `RANK_OUTSIDE_SWEET_SPOT`: 1
- blank / no current setup row in rendered set: 1

Corrected preview fail reasons:

- `SELECTION_STATE_NOT_ELIGIBLE`: 40

Newly rescued from rank sweet spot:

- `HYPE`

## HYPE Case

HYPE is the key example in this run:

- rank: `1`
- selection state: `WATCHLIST`
- current setup state: `FAIL`
- current fail reason: `RANK_OUTSIDE_SWEET_SPOT`
- corrected rank eligible: `true`
- corrected setup state preview: `PASS`
- corrected setup reason preview: `RANK_1_10_AND_MARKET_CONTEXT_OK`
- actionable cap preview: `ACTIONABLE_WITHIN_CAP`
- BTC prior 24h: `-0.01451735`
- preview notes: `TOP_RANK_PRIORITY`, `CHASE_RISK_PREVIEW`

The preview indicates that HYPE is blocked only because rank `1` is outside the current `4..10` setup sweet spot. Under rank `1..10` setup eligibility, it would pass the existing market context checks in this snapshot.

## Interpretation

The current `4..10` hard setup gate is likely inverted for setup-filter semantics.

The original intent was to avoid too many candidates becoming actionable at the same time. That is cardinality control, not technical setup validity. A top-ranked candidate should not fail setup purely because it is top ranked.

The cleaner split is:

- setup filter validates whether the market setup is technically valid.
- rank prioritizes candidates.
- paper advice policy preview or a later decision gate limits how many candidates can become actionable.
- decision gate remains account-aware and is not touched by this preview.

If rank `1..3` rows are risky because they are overextended or chase-prone, that should be proven with explicit overextension, distance, momentum, lifecycle, or market-state metrics. Rank alone is not a sufficient reason to fail a setup.

## Recommended Next Step

Open a separate reviewed implementation patch to remove the lower-rank exclusion from setup eligibility, most likely by changing setup rank eligibility from `4..10` to `1..10` or by removing the lower bound.

Keep top-rank handling as display/policy context only until backed by explicit chase-risk metrics.

Move max-actionable candidate control to paper advice policy preview or the account-aware decision gate. Do not promote any row to live or paper execution from this preview.

## Boundaries

This preview does not:

- change `trade_setup_filter_v1` production behavior
- change selection, advice, policy, decision, planning, execution, or broker behavior
- write to the database
- create orders
- authorize runtime promotion
