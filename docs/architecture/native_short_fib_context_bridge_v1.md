# Native SHORT Fib Context Bridge V1

## Purpose

`native_short_fib_context_v1` is the canonical market-only read contract for
SHORT fib context.

It exists so reporting surfaces such as Profit Plan can consume a stable native
`SHORT` context without:

- computing fib/swing logic inside reporting
- silently treating legacy `1d` fib rows as native SHORT
- wiring unstable research output files directly into operational reporting

## Canonical SHORT Definition

- `fib_trading_horizon=SHORT`
- `primary_interval=4h`
- `supporting_interval=1h`
- `4h` is authoritative
- `1h` is supporting only

The supporting `1h` lane may confirm, conflict, or show a breakout-gate retest.
It must not silently replace the active `4h` map.

Canonical supporting `1h` states:

- `ALIGNED_WITH_4H`
- `RETEST_SUPPORTIVE`
- `NEUTRAL_OR_NOT_CONFIRMING`
- `CONFLICT_WITH_4H`

`CONFLICT_WITH_4H` requires a genuine directional contradiction such as
invalidation-pressure or a materially broken breakout after a confirmed `4h`
map. It must not be used merely because the `1h` close is still below the
authoritative `4h` breakout gate.

## Layer Ownership

- market-only bridge builder: `src/market_data/native_short_fib_context_v1.py`
- runner / coverage audit: `src/market_data/run_native_short_fib_context_v1.py`
- read-only consumer: `src/reporting/run_manual_short_trader_profit_plan_v1.py`

No selection, decision, execution, broker-write, or account mutation path is
added in this batch.

## Row Contract

Canonical row fields:

- `symbol`
- `venue`
- `quote_currency`
- `fib_trading_horizon`
- `primary_interval`
- `supporting_interval`
- `context_status`
- `map_cycle_id`
- `anchor_start_ts_utc`
- `anchor_end_ts_utc`
- `anchor_low_price`
- `anchor_high_price`
- `breakout_gate_price`
- `latest_primary_close_ts_utc`
- `latest_support_close_ts_utc`
- `latest_primary_close_price`
- `ext_1_272_price`
- `ext_1_618_price`
- `ext_2_000_price`
- `active_target_levels_json`
- `previous_target_levels_json`
- `reload_r382_price`
- `reload_r500_price`
- `reload_r618_price`
- `reload_r786_price`
- `invalidation_price`
- `primary_4h_lifecycle_state`
- `supporting_1h_state`
- `context_freshness_status`
- `max_primary_high_since_anchor`
- `min_primary_low_since_anchor`
- `source_name`
- `source_version`
- `source_primary_ref`
- `source_support_ref`

## Context Status

Canonical builder status values:

- `NATIVE_SHORT_CONTEXT_AVAILABLE`
- `INSUFFICIENT_4H_HISTORY`
- `INSUFFICIENT_1H_HISTORY`
- `CONTEXT_INVALID_OR_STALE`
- `SYMBOL_CONTEXT_MISSING`

Representative primary `4h` lifecycle states:

- `BELOW_BREAKOUT_GATE`
- `BREAKOUT_CONFIRMED`
- `TARGET_ACTIVE`
- `TARGET_REACHED_OR_PASSED`
- `POST_BREAKOUT_PULLBACK`
- `MAP_COMPLETED`
- `INVALIDATED`

Rules:

- only `NATIVE_SHORT_CONTEXT_AVAILABLE` is native SHORT coverage
- `INSUFFICIENT_1H_HISTORY` keeps the `4h` map visible in the bridge output for
  audit, but reporting must not claim native SHORT availability from it
- `CONTEXT_INVALID_OR_STALE` covers stale windows or invalid latest-map state
- `SYMBOL_CONTEXT_MISSING` means no usable `1h` or `4h` candle source was found

## Profit Plan Contract

Profit Plan consumes this bridge read-only:

- native available row → `short_context_coverage_status=NATIVE_SHORT_CONTEXT_AVAILABLE`
- partial / insufficient native row → no native SHORT availability
- legacy `1d` fib-map may still be shown as `LEGACY_1D_CONTEXT_ONLY` reference
- missing native row remains `NO_NATIVE_SHORT_FIB_CONTEXT`

This preserves the truth boundary:

- market-only lifecycle/history is upstream
- account-aware order coverage remains reporting audit only

## Output Files

Default output directory:

`data/research/native_short_fib_context_v1/`

Files:

- `native_short_fib_context_rows_v1.csv`
- `native_short_fib_context_rows_v1.jsonl`
- `coverage_summary_v1.csv`
- `manifest_v1.json`

These are generated artifacts and must not be committed unless explicitly
requested and reviewed.
