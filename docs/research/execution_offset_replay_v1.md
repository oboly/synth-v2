# Execution Offset Replay v1

Issue #224 owns the shared research substrate for execution-offset studies.
This contract is research-only and does not change planner, executor, broker, or live behavior.

## Episode contract

Each immutable episode preserves market identity, source map identity, canonical Fib level, side, horizon, issuance time, validity window, invalidation, ATR-at-issue, and optional regime context.

Only candles whose full interval starts at or after `issued_ts_utc` and closes no later than `valid_until_ts_utc` may label an episode. A candle opened before issuance is excluded even if it closes later. Future candles are labels only.

When one OHLC candle spans both the candidate execution price and invalidation price before any prior fill, intrabar ordering is unknowable. The replay records `same_candle_fill_invalidation_ambiguous=true`, claims neither fill nor invalidation-before-fill, and stops that episode rather than inventing an order of events.

## Baseline policies

- `EXACT_LEVEL`: execution price equals canonical market level.
- `STATIC_BUFFER`: BUY moves above the level; SELL moves below the level by a fixed fraction.
- `VOLATILITY_SCALED_BUFFER`: same side semantics, with offset derived from ATR known at issuance.

The canonical Fib level is never rewritten.

Near-miss distance is policy-specific: it is measured against the candidate `execution_price`, while the raw canonical level remains separately preserved for audit. MFE/MAE starts only on candles strictly after the fill candle because OHLC cannot establish whether an excursion inside the fill candle occurred before or after the fill.

`touched` is policy-specific and means the candidate execution price was reached/crossed. `canonical_level_touched` separately preserves whether the raw Fib level itself traded inside a candle range. Therefore a buffered fill may have `touched=true` and `canonical_level_touched=false` without conflating market truth and execution policy.
