# TODO — Native SHORT Invalidation Confirmation Backtest v1

> **Migration pointer.** Current execution status, priority, blockers,
> acceptance criteria, and closure for this lane are owned by GitHub Issue
> [#220 — Replay native SHORT invalidation-confirmation policies](https://github.com/oboly/synth-v2/issues/220).
> This file is retained as frozen historical/design context; the status and
> task text below is preserved but superseded operationally by Issue #220.
> Do not update status, priority, blockers, next action, or execution order
> here. See `docs/development/github_issues_workflow.md`,
> `docs/todo/MIGRATION_FREEZE.md`, and
> `docs/development/github_issues_batch_2a_migration_v1.md`.

## Status

Open research / calibration lane.

## Triggering observation

Observed on 2026-07-17 for AAVE-EUR:

```text
reference invalidation: below 78.93 EUR
observed intraday low: approximately 78.44 EUR
breach depth: approximately 0.6%
subsequent behavior: immediate reclaim above 78.93 EUR and continued trading mostly above the level
Profit Plan authority: reporting fallback / native map data unavailable
```

The screenshot is not proof of a production defect because the visible card used a non-canonical reference and explicitly reported unavailable native map authority. It is valid evidence for a research hypothesis: wick-only invalidation may classify liquidity sweeps as structural map failures too aggressively.

## Hypothesis

The invalidation level itself may be acceptable while the confirmation rule is too strict.

Do not assume:

```text
low < invalidation
-> definitively invalidated
```

Research candidate state model:

```text
wick below invalidation
-> INVALIDATION_TESTED / BREACH_PENDING

reclaim before confirmation
-> FALSE_BREAK_RECLAIMED

confirmed close below invalidation
-> INVALIDATED
```

This is a research contract only. The final state names and thresholds remain unapproved until replay evidence exists.

## Required backtest

Run a leak-free, map-cycle-aligned replay using immutable native SHORT map geometry and later candle paths.

Compare at least these invalidation policies:

1. Any wick below the published invalidation level.
2. One completed 1h close below the level.
3. Two consecutive completed 1h closes below the level.
4. One completed 4h close below the level.
5. Wick below an ATR-normalized buffer beneath the level.
6. Close below an ATR-normalized buffer beneath the level.

The evaluator must never use future candles to determine the state at the current candle.

## Required measurements

For every breach candidate measure:

```text
map_cycle_id
symbol
setup family
primary timeframe
supporting timeframe
published invalidation
breach timestamp
breach depth pct
breach depth in ATR units
first close below timestamp
reclaim timestamp
candles to reclaim
maximum adverse excursion after breach
maximum favorable excursion after reclaim
target reached after breach
next target reached after breach
structural breakdown confirmed
map terminal state
source authority and freshness
```

Aggregate outputs:

```text
sample count
wick-breach count
close-confirmed breach count
false-break reclaim rate
reclaim within 1 / 2 / 4 candles
post-reclaim target-hit rate
true-breakdown detection rate
false invalidation rate
missed breakdown rate
extra adverse excursion caused by delayed confirmation
median and tail breach depth
results by volatility / liquidity / regime / setup / timeframe
```

## Decision criteria

A confirmation policy may replace wick-only invalidation only when it improves false-break handling without creating unacceptable delayed-loss recognition.

Evaluate the trade-off explicitly:

```text
fewer false invalidations
versus
later confirmation of genuine breakdowns
```

Require out-of-sample evidence across multiple assets and regimes. AAVE is an example, not a tuning target.

## Initial research preference

The first candidate to test is:

```text
wick below level
-> block new entries and mark BREACH_PENDING

1h close below level
-> provisional invalidation

4h close below level or two consecutive 1h closes below level
-> confirmed invalidation

reclaim before confirmation
-> FALSE_BREAK_RECLAIMED
```

Do not promote this preference without the comparative backtest.

## Architecture boundary

This work belongs to native SHORT market/map lifecycle research.

```text
selection_engine  = unchanged
 decision_gate     = unchanged
execution_planner = unchanged
executor / agents = unchanged
reporting          = persisted-state consumer only
```

Reporting must not derive or overwrite invalidation truth from chart appearance or fallback geometry.

## Guardrails

- Do not move invalidation levels farther away merely to avoid wick breaches.
- Do not tune from isolated screenshots.
- Do not rewrite immutable historical map geometry.
- Do not infer canonical lifecycle truth from reporting fallback cards.
- Do not add account, wallet, order, broker, decision, planning, or execution behavior.
- Do not introduce live or paper trading authority.
- Keep the evaluator read-only and account-agnostic.

## Definition of done

- Leak-free replay implemented.
- Immutable map-cycle alignment proven.
- All candidate confirmation policies compared on identical samples.
- False-break and delayed-breakdown trade-offs quantified.
- Results stratified by asset, regime, volatility, setup, timeframe, map age, and source authority.
- One recommendation documented with out-of-sample evidence.
- No runtime promotion until a separate reviewed implementation PR.
