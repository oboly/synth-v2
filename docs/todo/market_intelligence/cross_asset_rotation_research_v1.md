# Cross-Asset Rotation Research v1

## Status

```text
open P3 market-only research
non-blocking
manual execution remains outside Synth
```

## Purpose

Measure whether participation is rotating from crypto or broad risk assets into metals, miners, or food/agriculture using accepted canonical public observations.

This lane answers market questions only. It does not decide what an account should buy, size, permit, plan, or execute.

## Inputs

Consumes accepted records from:

```text
../external_research/cross_asset_public_data_and_instrument_registry_v1.md
```

Required input properties:

- neutral `instrument_key`;
- explicit rotation group;
- absolute observation timestamps;
- freshness and provenance;
- listing/price currency;
- exchange timezone and session calendar;
- explicit missing/stale states.

## Research groups

```text
METALS
MINERS
FOOD_AGRICULTURE
```

## Snapshot contract

```text
instrument_key
rotation_group
observed_at_utc
return_1d
return_7d
return_30d optional
relative_strength
volume_state where meaningful
trend_state
rotation_pressure_state
freshness_state
reason_codes
```

## Normalization requirements

Do not directly compare crypto and securities observations without explicit handling of:

- trading hours, weekends, and holidays;
- currency and FX effects;
- session gaps and missing bars;
- volume meaning;
- corporate actions;
- fund and ETC tracking structure.

Rank instruments within comparable groups first. A later group-level comparison must use an explicit clock and normalization contract.

## Research questions

- Is participation moving from crypto toward metals?
- Are miners confirming or diverging from the underlying metal?
- Is food/agriculture strength broad or isolated?
- Does strength persist after FX and session normalization?
- Does the signal survive realistic transaction-cost assumptions?

## Replay and validation

Before stronger user language or any promotion into `selection_engine`, measure:

- forward return by rank and group;
- MFE/MAE;
- persistence and false-rotation rate;
- metals/miners lead-lag;
- food/agriculture breadth;
- regime dependence;
- spread, commission, FX, TER, tracking difference, and slippage sensitivity;
- weekly versus faster cadence;
- buy-and-hold and equal-weight controls.

A separate validated promotion decision is required before these outputs become canonical selection features.

## Reporting boundary

A read-only dashboard may later display accepted persisted snapshots. It must not recompute canonical classifications, imply broker-position knowledge, or call a broker.

## Architecture boundary

```text
market research     = market-only and account-agnostic
selection_engine    = unchanged until separately validated promotion
decision_gate       = unchanged
execution_planner   = unchanged
executor / agents   = unchanged
broker clients      = absent
manual broker trade = human action outside Synth runtime
```

## Acceptance

- deterministic replayable calculations;
- explicit stale/null behavior;
- session- and FX-aware normalization;
- no account or broker dependency;
- no order or execution authority;
- documented evidence before any feature promotion.