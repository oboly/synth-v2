# Asset Profile Layer V1

## Purpose

The asset profile layer separates static asset identity from derived market behavior.

`asset` should remain mostly static.

`asset_profile_snapshot` stores derived point-in-time profiles.

## Boundary

Allowed:

    read market candles
    derive liquidity class
    derive beta profile
    store point-in-time profile snapshots
    expose latest profile view for live/research convenience

Forbidden:

    no order handling
    no execution_plan writes
    no decision_state writes
    no account balance mutation
    no future-aware labels
    no sector clusters without empirical support

## Data model

Static identity:

    asset

Derived profile:

    asset_profile_snapshot

Convenience view:

    vw_asset_profile_latest

## Field meaning

liquidity_class:

    derived tradability / liquidity tier

beta_profile:

    derived sensitivity / volatility behavior versus market benchmark basket

sector_group_code:

    intentionally null in v1
    later derived from empirical co-movement and trend timing alignment

market:

    venue/quote tradable instrument concept, separate from profile

## Backtest rule

Live or current research may use `vw_asset_profile_latest`.

Backtests and replay must use the profile snapshot with:

    asset_profile_snapshot.asof_ts_utc <= replay_asof_ts_utc

Never use latest profile inside historical replay.

## Current v1 scope

Implemented:

    liquidity_score
    liquidity_class
    beta_to_market
    beta_profile
    realized_volatility
    coverage_ratio

Not implemented yet:

    sector clustering
    point-in-time profile joins inside selection/replay
    decision gate integration
    execution planner integration
