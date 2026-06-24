# Profit Plan Breath Curve Live V1

The live Profit Plan card now uses the market-only Breath Curve matcher stack, not the Market Breath V1 phase/state classifier.

## Payload

Each Profit Plan symbol JSON row includes `breath_curve` with:

- `availability_state`: `AVAILABLE`, `STALE`, or `UNAVAILABLE`
- `as_of_ts_utc`: requested live read timestamp for the provider
- `source_candle_ts_utc`: last closed daily candle actually used
- `freshness_label`: `FRESH`, `STALE`, or `UNAVAILABLE`
- `phase_marker`: current matcher checkpoint code when available
- `phase_offset_days`: selected phase offset from the matcher/progression layer
- `phase_offset_band`: calibrated offset band from the existing phase-band helper
- `template_match_score`: current as-of template-match quality
- `current_checkpoint`: current matched checkpoint code
- `next_checkpoint`: next expected checkpoint code
- `next_target_expected_ts_utc`: expected timing for the next checkpoint
- `next_target_is_future`: whether that next checkpoint still lies ahead of the current as-of
- `lead_lag_vs_btc`: BTC offset relation when BTC can be resolved from the same market-only candle snapshot
- `data_coverage`: closed-candle coverage summary
- `warnings`: read-only diagnostics

Matcher vocabulary remains the existing checkpoint set:

- `FIRST_LIFT_HIGH`
- `FIRST_DIP_LOW`
- `SECOND_PEAK_RETEST_HIGH`
- `SECOND_DIP_HIGHER_LOW`
- `IGNITION_PRE_SPIKE`
- `MAIN_PULSE_TP_HIGH`
- `OVERSHOOT_EXTENSION_TP`

## Boundaries

- Runtime uses only closed daily market candles plus BTC candles for optional relative offset context.
- The live provider is market-only and deterministic for a given symbol set plus as-of timestamp.
- No A+ inputs, raw text, research DB rows, account data, wallet state, orders, execution state, or trading decisions enter the provider.
- No research CLI or backtest runner is invoked from the Profit Plan request path.
- If the provider cannot resolve enough honest closed-candle context or an anchor candidate, it returns `UNAVAILABLE` with warnings instead of fabricating a checkpoint.
- Breath Curve output on the Profit Plan card is context only. It is not a forecast, trade signal, or execution instruction.
