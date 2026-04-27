# Parking Rotation Recovery V1

## Status

`research_candidate_positive_walk_forward`

This policy is a research candidate only.

It is not live.
It is not a decision gate rule.
It is not an execution rule.

## Boundary

Layer:

`research / strategy-candidate evaluation`

Allowed:

- market-only replay evaluation
- selection/ranking/context policy testing
- future strategy-module simulation

Forbidden:

- account balances
- positions
- open orders
- execution plans
- broker actions

## Policy definition

Name:

`parking_rotation_recovery_v1`

Concept:

24h recovery / mean-reversion pulse inside assets classified as market-exit/no-trade by ranking context.

This is not a trend-following policy.

Core rule:

```text
selection_state = WATCHLIST
priority_rank BETWEEN 4 AND 10
btc_prior_24h BETWEEN -0.010 AND 0.010
selection_score < 0.50000000
symbol NOT IN weak set
rotation_bucket = ROTATION_EXIT
classification_code = NO_TRADE
sleeve_fit_code = EXPERIMENTAL
