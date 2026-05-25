## INTRADAY_RETEST_RECLAIM_V1

`INTRADAY_RETEST_RECLAIM_V1` is the first live-like strategy family proposed for Synth v2.12 shadow mode.

It is intentionally narrow:

- market-only
- intraday
- reclaim and retest oriented
- preview-only in phase 1

This document defines the strategy concept, not a live trading implementation.

## Strategy Idea

The strategy looks for:

- impulse or reclaim behavior on a primary timeframe
- evidence that the move is active rather than fully exhausted
- a later shallow, normal, or deep retest on a lower entry timeframe

The strategy emits candidate states only. It does not place orders, reserve capital, or bypass account-aware permissions.

## Timeframe Roles

Initial intended roles:

- context timeframe: `4h`
- primary timeframe: `1h`
- entry timeframe: `15m`

These are instance-level configuration values, not hardcoded family rules.

## Candidate-State Semantics

- `NO_CANDIDATE`: no useful reclaim/retest structure exists
- `WATCH_FOR_RECLAIM`: context is interesting, but reclaim structure is not confirmed
- `IMPULSE_ACTIVE`: an active directional impulse exists
- `WAIT_RETEST`: impulse exists, but no acceptable retest is present yet
- `SHALLOW_RETEST_ACTIVE`: shallow retest is active
- `NORMAL_RETEST_ACTIVE`: normal retest is active
- `DEEP_RETEST_ACTIVE`: deep retest is active
- `ENTRY_CANDIDATE`: market/setup side is ready for downstream review
- `INVALIDATED`: reclaim/retest structure is broken
- `STALE`: candidate is too old to trust without refresh

`ENTRY_CANDIDATE` is still not a buy permission. It only means the market/setup side is ready for decision review.

## Watcher Mapping

The existing public-market watcher vocabulary is a useful precursor:

- `IMPULSE_CONTINUATION`
  - maps to `IMPULSE_ACTIVE` or `WAIT_RETEST`
- `WICK_REJECTION_PULLBACK`
  - maps to `WAIT_RETEST`
- `SHALLOW_PULLBACK_STRONG`
  - maps to `SHALLOW_RETEST_ACTIVE`
- `NORMAL_RETEST_ZONE`
  - maps to `NORMAL_RETEST_ACTIVE`
- `DEEP_RETEST_ZONE`
  - maps to `DEEP_RETEST_ACTIVE`
- `NO_CLEAN_ENTRY`
  - maps to `NO_CANDIDATE`

This keeps the strategy family generic while allowing continuity from existing manual-watch tooling.

## Safety Boundaries

The strategy family must remain inside the market-only lane.

- no account reads are required to form a candidate
- no broker writes
- no order submission
- no decision gate bypass
- no execution planner bypass
- no account sizing logic inside strategy generation

Anything account-aware starts only after a `StrategyCandidate` is produced and passed into a preview/decision layer.

## First Configured Instance

The first configured instance is:

- `near_intraday_retest_reclaim_v1`

This does not make the strategy NEAR-specific. It is only the first enabled instance.

Later examples should be config-driven:

- `hype_intraday_retest_reclaim_v1`
- `render_intraday_retest_reclaim_v1`

The strategy family code should not fork on symbol.

## Phase 1 Outcome

Phase 1 only needs to make the following architecture path concrete:

- strategy instance config
- strategy candidate contract
- decision preview contract
- execution-plan preview contract
- shadow event contract

That gives Synth a live-like but still non-trading vertical slice.
