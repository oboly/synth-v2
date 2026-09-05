# MA / Volume Candidate Validation v1

Issue: #310
Status: research-only candidate feature preparation

## Purpose

Prepare replay-safe raw MA/volume measurements for historical validation before
any trend/volume classification vocabulary, dashboard band, or production
selection use is considered.

This slice does not replace the canonical MA50 breadth producer merged in PR
#715. It addresses the remaining per-asset research scope in #310.

## Reuse decision

`src/features/candle_feat_builder.py` already owns the generic rolling SMA and
volume-ratio primitives:

- arbitrary `sma_windows` can produce SMA50, SMA150 and SMA200 without a second
  MA implementation;
- `volume_ratio_20` is already produced through `volume_sma_window=20`.

The research candidate builder therefore consumes those primitives through the
existing builder. It does not reimplement rolling moving averages or volume
ratio.

Repository audit found no canonical `volume_zscore` primitive on current main.
This slice deliberately does not invent one. A later validation slice may add a
separately reviewed primitive only if the research design proves it is needed.

## Candidate measurements

For one market and the canonical 4h input interval, the builder exposes:

```text
SMA50
SMA150
SMA200
close_vs_sma50_pct
close_vs_sma150_pct
close_vs_sma200_pct
sma50_slope_pct_<N>b
sma150_slope_pct_<N>b
sma200_slope_pct_<N>b
bullish_ma_stack
volume_ratio_20
```

`bullish_ma_stack` is the raw relation `SMA50 > SMA150 > SMA200`; it is not a
trend classification or trade signal.

Slope length is an explicit research parameter, defaulting to 6 bars. It is
persisted in the candidate frame metadata and must not be treated as a validated
production setting merely because it is the default research candidate.

## Point-in-time boundary

`asof_ts_utc` is mandatory. Candles with `end_ts > asof_ts_utc` are removed
before rolling features are built. No latest-row fallback is allowed.

The current research builder accepts exactly one market and one 4h interval per
call. Mixing markets is rejected instead of relying on accidental grouping or
caller ordering.

## Explicitly not produced

No state vocabulary or threshold is defined here, including:

```text
TREND_ALIGNED
TREND_RECOVERY
MA_RECLAIM_PENDING
TREND_DAMAGED
VOLUME_EXPANDING
VOLUME_CONTRACTING
```

No gauge/color bands, ranking weights, selection score, regime state,
account-aware permission or execution intent are produced.

## Next validation slice

Historical validation should bind frozen outcome labels separately from the
candidate feature frame and compare incremental information against the existing
baseline. At minimum, evaluate whether retained MA150/200 position/slope/stack
and volume-ratio measurements add value beyond current structure, RSI/Fib room
and Rotation evidence.

Any categorical threshold must be learned/selected only inside a documented
train/discovery partition and then tested unchanged on non-overlapping
validation/holdout data. Failure to show incremental value should result in
feature rejection rather than dashboard promotion.

## Safety

```text
research_only=1
market_only=1
account_awareness=0
selection_engine_change=0
decision_gate_change=0
execution_planner_change=0
executor_change=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_activation=0
production_writer_change=0
reporting_change=0
```
