# Selection Context Filter V1 — Research Notes

## Status

Research / paper-trade candidate only.

This is not yet a live execution rule.

## Core finding

Selection Engine V2 currently behaves more like a market radar than a direct entry signal.

Raw WATCHLIST / PREPARE states are not sufficient as trade triggers.

## Candidate setup

Market-only context filter:

- selection_state = WATCHLIST
- priority_rank between 4 and 10
- BTC prior 24h return between -1.5% and +1.5%
- evaluation horizon: 24h
- fee model used: 25 bps per side, 50 bps round-trip

Observed result:

- n_24h = 437
- avg_net_24h = +0.6103%
- win_24h = 51.95%

Fail bucket:

- avg_net_24h = -1.1097%
- win_24h = 29.93%

## Interpretation

The edge appears in non-overheated continuation / rotation conditions.

Bad zones:

- BTC prior 24h > +1.5%: overheat / FOMO zone
- BTC prior 24h < -1.5%: damage zone
- priority_rank 1-3: often too obvious / late
- priority_rank 11-20: too weak / noisy

Best observed balance:

- rank 4-10
- BTC prior 24h between -1.5% and +1.5%

## Variant comparison

- rank 4-10, BTC ±1.5%: +0.6103%, win 51.95%
- rank 1-10, BTC ±1.5%: +0.4679%, win 50.08%
- rank 4-20, BTC ±1.5%: +0.2836%, win 47.81%
- rank 4-10, BTC ±1.0%: +0.6013%, win 52.13%
- rank 4-10, BTC ±2.0%: +0.2321%, win 48.80%

Conclusion:

Use ±1.5% as baseline research setting. ±1.0% does not improve enough to justify the lower sample size.

## Asset suitability candidate

Post-hoc weak set tested:

- HNT
- SOL
- XLM
- LTC
- ETH
- XRP
- CC
- NOT

Sweet spot with this weak-set excluded:

- n_24h = 302
- avg_net_24h = +1.0960%
- win_24h = 59.93%

Excluded weak set:

- n_24h = 135
- avg_net_24h = -0.4763%
- win_24h = 34.07%

This is promising but overfit-risky. Treat as an asset suitability candidate, not as a permanent blacklist.

## Architecture placement

Correct placement:

selection_engine_v2
→ market radar / attention layer

trade_setup_filter_v1
→ market-only tradability / trigger-context filter

decision_gate
→ account-aware permission layer

execution_planner
→ execution intent only

Do not place this logic in decision_gate or execution_planner.

## Next research steps

1. Add exclusion / asset suitability options to the evaluator.
2. Run paper-only context filter candidate.
3. Compare against future unseen snapshots.
4. Later promote to trade_setup_filter_v1 only if out-of-sample behavior holds.
