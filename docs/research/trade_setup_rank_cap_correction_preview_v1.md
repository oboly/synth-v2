# Trade Setup Rank Cap Correction Preview V1

## Status

Production correction prepared for `trade_setup_filter_v1`. The change is limited to market-only setup eligibility.

Safety markers:

- broker_private_calls=0
- broker_writes=0
- order_submission=0
- live_orders=0
- decision_gate_changes=0
- execution_planner_changes=0
- executor_changes=0

## Problem

The prior setup-filter rank gate used rank `4..10` as a hard setup sweet spot. That made rank `1`, `2`, and `3` fail setup purely because they were top-ranked.

The diagnostic case was HYPE:

- selection state: `WATCHLIST`
- rank: `1`
- old fail reason: `RANK_OUTSIDE_SWEET_SPOT`

That behavior was inverted relative to the original intent.

## Architectural Interpretation

Rank has two different meanings:

- setup filter: validate whether a market setup is technically eligible.
- downstream policy / decision layers: prioritize and limit how many candidates become actionable.

The original goal was cardinality control, not top-rank rejection. Rank `1..3` should be prioritized, not failed by rank alone.

## Production Correction

`trade_setup_filter_v1` now treats rank `1..10` as setup-eligible. Rank outside that range fails with `RANK_OUTSIDE_SETUP_ELIGIBLE_RANGE`.

Top-ranked rows can still carry context in `notes`:

- `rank_context=TOP_RANK_PRIORITY`
- `chase_risk_context=REVIEW_METRICS`

These notes are not strategy rules and do not make rows actionable.

## Preview Runner

The preview runner compares:

- legacy `4..10` behavior
- corrected production `1..10` behavior
- downstream `max_actionable` cap preview

Command:

```bash
python -m src.research.run_trade_setup_rank_cap_correction_preview_v1 \
  --venue bitvavo \
  --interval 4h \
  --limit 80 \
  --max-actionable 3 \
  --output table
```

Current smoke observation on `2026-05-18`:

- legacy HYPE fail reason: `RANK_OUTSIDE_SWEET_SPOT`
- corrected HYPE fail reason: `MARKET_DAMAGE_RISK`
- rank gate removed: `true`
- corrected setup PASS count: `0`

The corrected PASS count stayed at zero in that smoke because BTC prior 24h was slightly below the damage threshold. That is a separate market-context guard, not a rank failure.

## Expected Result

HYPE should no longer fail only because rank is `1`. Setup PASS count may increase if HYPE still satisfies the other market-only guards.

If HYPE moves from legacy `RANK_OUTSIDE_SWEET_SPOT` to another guard such as `MARKET_DAMAGE_RISK`, the rank inversion is still corrected. That means the rank gate was removed, but the setup can remain invalid for non-rank market context.

Actionable count limiting remains downstream. This patch does not add a max-actionable cap to `trade_setup_filter_v1`.

## Next Step

Review the corrected setup-filter output after the next 4h chain run. If too many rows become actionable, add or review caps in paper advice policy preview or the account-aware decision gate. Do not put cardinality control back into setup eligibility.
