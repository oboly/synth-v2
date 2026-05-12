# Synth v2.7 4h Chain Smoke Status — 2026-05-12

## Status

Result: PASS

The full 4h market-only chain completed successfully.

Repository state after run:

    main == origin/main
    working tree clean
    HEAD = 1e52cdc Refresh execution zone context in 4h chain

## Chain result

The 4h chain completed through:

    candles ETL
    feat_candle
    signal_state
    advice_engine
    ranking_engine
    asset_interval_quality_snapshot
    selection_engine_v2
    execution zone context refresh
    trade_setup_filter_v1
    trade_setup_filter_policy_preview_v1
    strategy_runtime_snapshot

Final runtime snapshot:

    strategy_runtime_snapshot latest_ts = 2026-05-12 13:59:44

## Execution zone context freshness

Operational execution zone context is now refreshed inside:

    scripts/run_chain_4h.sh

Latest verification:

    execution_zone_context rows = 41
    latest context asof = 2026-05-12 12:00:00
    context_bad_rows = 0

All enabled tradeable assets have fresh 4h execution context.

## Asset universe correction

TON was intentionally disabled:

    TON is_enabled   = 0
    TON is_tradeable = 0
    TON is_portfolio = 0

LINK remains active:

    LINK is_enabled   = 1
    LINK is_tradeable = 1
    LINK is_portfolio = 1

## Trade setup table name correction

The verification check initially looked for:

    trade_setup_filter_result

That table does not exist and is not the current canonical table.

Actual current tables:

    trade_setup_filter_observation
    trade_setup_policy_preview_observation

Latest observed rows:

    trade_setup_filter_observation rows = 9080
    latest asof_ts_utc = 2026-05-12 13:59:25.006973

    trade_setup_policy_preview_observation rows = 405
    latest asof_ts_utc = 2026-05-12 13:59:25.006973

So the missing trade_setup_filter_result table was a stale verification-name issue, not a runtime failure.

## Current 24H policy preview

Latest pass rows:

    NEAR  -> WATCH_ONLY
    FLOKI -> WATCH_ONLY
    TAO   -> INSUFFICIENT_SAMPLE
    DEEP  -> INSUFFICIENT_SAMPLE
    MOG   -> BLOCK_FOR_24H

Runtime allowed now:

    NONE

This is correct: the chain remains market-only and no live order path is enabled.

## Safety

Broker write permission remained absent.

No broker writes, no order submission, no executor path.

## Note on PyMySQL cursor traces

cursors.py stack traces came from PyMySQL internals. They do not indicate a project file that needs patching.

The stale table check should use:

    trade_setup_filter_observation
    trade_setup_policy_preview_observation
