# Target Capture Calibration Analysis V1 (#559 Phase B)

## Purpose

This is the deterministic research-only calibration layer for #559. It consumes the #555 -> #224 adapter output from `target_capture_calibration_adapter_v1` and delegates all fill/near-miss replay to the shared #224 replay engine. It does not rebuild Fib geometry, replay candles, order semantics, or runtime behavior.

## Frozen candidate set

The candidate set is fixed before historical-result inspection: `0%`, `0.5%`, `0.75%`, `1.0%`, `1.25%`, `1.5%`. `0%` is `EXACT_LEVEL`; non-zero candidates are `STATIC_BUFFER`. Raw/canonical target values are never mutated. Every evidence row carries both `raw_canonical_level` and `executable_level`.

## Required-buffer distribution

For the exact policy, an unambiguous raw target hit/touch requires `0` percentage points of buffer. An unambiguous raw-target miss uses #224 `near_miss_distance_pct`. Exact same-candle fill/invalidation ambiguity is excluded from resolved quantile and candidate cohorts and reported explicitly. Quantiles P50/P75/P80/P90 use deterministic nearest-rank selection `ceil(p*N)` over Decimal values.

## Candidate economics

For each candidate the report includes resolved sample count, candidate ambiguity count/rate, fill/capture rate, capture-rate uplift versus exact, average foregone upside among filled episodes, expected foregone-upside contribution across resolved episodes, expected captured-return proxy, and delta versus exact.

Expected captured return is normalized to the immutable #555 reference price: bullish SELL target `(execution_price-reference_price)/reference_price*100`; bearish BUY target `(reference_price-execution_price)/reference_price*100`; unresolved/non-filled rows contribute zero. Foregone upside is the absolute raw-to-executable target displacement as a percentage of raw target.

## Segmentation and confidence

Reports include overall plus `fib_level_id`, `horizon`, and `direction` segments. Each segment has `SUFFICIENT_SAMPLE` or `INSUFFICIENT_SAMPLE` against the positive-integer minimum threshold. ATR availability is reported, but no ATR/volatility bins are invented because Synth does not yet have a canonical volatility-bin contract for this research lane. `map_state` and `map_confidence` remain unrelated to market regime.

## Disposition

The overall sample must first meet the minimum threshold, otherwise disposition is `RESEARCH_ONLY`. Among non-zero buffers, a candidate is viable only when both capture-rate uplift and expected-return delta versus exact are positive. If none is viable, disposition is `REJECT`. Otherwise choose highest expected captured-return proxy, with lower buffer as deterministic tie-break. If any sufficiently sampled Fib-level, horizon, or direction subgroup has a negative expected-return delta for the selected candidate, downgrade to `RESEARCH_ONLY`; otherwise disposition is `EXECUTION_PLANNER_CANDIDATE`.

This disposition is research evidence only. It does not grant execution permission and does not configure `execution_planner`. Promotion requires a separate reviewed path; #317 remains the later read-only/paper-validation lane.

## Safety boundary

`research_only=1`, `account_awareness=0`, `decision_permission=0`, `execution_intent=0`, `broker_writes=0`, `order_submission=0`, `runtime_activation=0`.
