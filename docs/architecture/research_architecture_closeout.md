# Research Architecture Closeout

## Status

The research workflow is now clear enough to treat as a stable architectural direction.

This does **not** mean we already have a production-ready signal.

It means we now have a cleaner way to test, reject, refine, and later promote signal ideas.

---

## Confirmed Direction

Research should proceed from known pattern families first.

Canonical flow:

Known Pattern Family
-> State Definition
-> Trigger Definition
-> Forward Return Evaluation
-> Regime Split
-> Keep / Kill / Refine

This flow is now the standard.

---

## Architectural Separation

### Research layer

Research code belongs under:

src/research/
    pattern_families/
    trigger_tests/
    evaluation/

### Production layer

Production-facing logic remains separate:
- signal_engine_state
- interpreter_state
- strategy_signal
- decision_state

Research should not be merged directly into production logic before passing a clear promotion threshold.

---

## Responsibility of Each Research Folder

### src/research/pattern_families/

Purpose:
- define broad, known market pattern families
- create initial state + trigger baseline
- run first clean forward-return test

Examples:
- trend_pullback_continuation_4h
- volatility_compression_breakout_4h
- failed_breakout_4h

A pattern family is not yet a production signal.

---

### src/research/trigger_tests/

Purpose:
- refine timing logic on top of an existing family
- test entry variants
- compare raw family vs triggered family

Examples:
- reclaim trigger
- breakout hold trigger
- no-new-low trigger
- T+1 entry / T+2 exit

This is where "family" becomes more trade-like.

---

### src/research/evaluation/

Purpose:
- reusable evaluation utilities
- summary and comparison logic
- recent vs full window comparison
- regime split evaluation
- bucket summaries
- horizon sweeps later

This code should be reusable across multiple families.

---

## Canonical Research Concepts

### Pattern Family
A known market behavior class.

Examples:
- trend continuation pullback
- volatility compression breakout
- failed breakout reversal
- sweep and reverse

### State
Context that describes when the family may exist.

Examples:
- EMA relationship
- volatility regime
- participation / volume regime
- higher timeframe alignment
- relative strength
- market regime

### Trigger
Entry timing event inside the state.

Examples:
- close above compression range
- reclaim after pullback
- close back inside failed breakout range
- first continuation candle

### Evaluation
Explicit forward-return measurement.

Examples:
- next_return_4h
- next_return_8h
- recent-window summary
- regime-specific performance

---

## Naming Rules

### Prefer explicit forward return names
Use:
- next_return_4h
- next_ts_utc
- entry_close_price
- next_close_price

Avoid:
- ad hoc aliases
- naming drift across scripts
- multiple names for the same concept

### Prefer explicit family names
Use:
- TREND_PULLBACK_CONTINUATION_4H_V1
- VOLATILITY_COMPRESSION_BREAKOUT_4H_V1
- FAILED_BREAKOUT_4H_V1

---

## Verdict Rules

Every tested family must end with one verdict:

- KEEP
- KILL
- REFINE

### KEEP
Clear, robust, interpretable behavior.

### KILL
Negative or non-usable after basic testing.
Stop spending more time on it.

### REFINE
Structurally plausible but too broad, too strict, or missing trigger/state refinement.

---

## What Current Research Established

### Strong process wins
- research views with explicit forward returns are necessary
- recent-window testing matters
- regime split matters
- known-family-first workflow is faster than rediscovering signals from scratch

### Strong conceptual lessons
- family does not equal signal
- context does not equal entry
- trigger layer is essential
- top examples alone are not enough
- clean average behavior matters more than attractive outliers

---

## Current Family Status

### KILL
- REVERSION_EXTREME_* direct family variants
- REVERSION_EXTREME + low participation
- REVERSION_EXTREME + ATR filter
- REVERSION_EXTREME + liquid/watchlist filter
- REVERSION_EXTREME + T+1 / T+2 timing

### REFINE
- TREND_PULLBACK_CONTINUATION_4H_V1
- VOLATILITY_COMPRESSION_BREAKOUT_4H_V1

Reason:
These families remain plausible, but current versions are not yet promotable.

---

## Promotion Rule

A family should not move into production-facing signal logic until it survives:

1. no-lookahead evaluation
2. recent-window testing
3. at least one regime split where relevant
4. stable naming and reproducible evaluation
5. explicit decision that it is:
   - context only
   - trigger only
   - or actual candidate signal

---

## Immediate Next Architectural Direction

The next family to prioritize should come from a structurally clean known family, such as:
- failed_breakout_4h
- refined volatility_compression_breakout_4h_v2

The choice should favor:
- clarity
- testability
- explicit trigger logic
- lower ambiguity than recent reversion branches


---

## Updated Family Status

### KEEP / PRIORITY
- FAILED_BREAKOUT_4H_V1

Reason:
This family produced clearly negative next 4h forward returns after failed upside breakout structure.

Observed recent-window result:
- count: 389
- avg next_return_4h: -0.020247
- median next_return_4h: -0.018464
- OTHER avg next_return_4h: 0.000170

Architectural interpretation:
This is not a long-entry family.
It is currently best understood as:
- avoid-long family
- reversal / short-context family
- risk overlay against breakout chasing

This is the first family from the current round that is strong enough to keep as a real candidate for later promotion.

### Current Family Summary

KEEP:
- FAILED_BREAKOUT_4H_V1

REFINE:
- TREND_PULLBACK_CONTINUATION_4H_V1
- VOLATILITY_COMPRESSION_BREAKOUT_4H_V1

KILL:
- REVERSION_EXTREME_* direct family variants
- REVERSION_EXTREME + low participation
- REVERSION_EXTREME + ATR filter
- REVERSION_EXTREME + liquid/watchlist filter
- REVERSION_EXTREME + T+1 / T+2 timing


---

## Failed Breakout Deployment Semantics

### Pattern family
- FAILED_BREAKOUT_4H_V1

### Current interpretation
This is a bearish structural event family.

It should not be treated first as a direct short execution family.

Its first practical deployment role should be:

- risk overlay
- avoid-long family
- bearish context state

### Why this order is preferred

Observed behavior:
- materially negative next 4h forward return after failed upside breakout
- strong enough to matter
- not yet enough execution-specific testing for direct short deployment

This makes it immediately valuable as a defensive signal even before short infrastructure is formalized.

### Recommended deployment order

#### Phase 1
Use as:
- avoid-long signal
- anti-breakout-chase filter
- negative context modifier on bullish setups

#### Phase 2
Promote into:
- bearish structure state
- interpreter / context layer
- ranking / advice / risk influence

#### Phase 3
Only later, after more testing:
- short candidate family
- dedicated bearish execution logic

### Architectural landing point

Preferred first landing:
- interpreter_state
or
- strategy_signal_context

Not first landing:
- direct execution logic
- direct portfolio sizing logic without context layer

### Suggested semantics

Family meaning:
- breakout attempt failed
- upside continuation quality invalidated
- bearish follow-through probability increased

This should influence:
- long setup confidence downward
- breakout continuation confidence downward
- bearish context score upward

### Suggested first-use effects

Examples:
- lower long ranking score
- lower advice confidence for breakout longs
- mark as avoid-chase context
- raise risk sensitivity for fresh long entries

### Suggested initial fields

Possible fields to add later:
- breakout_failure_state
- failed_breakout_flag_4h
- bearish_failure_context_score
- avoid_long_overlay_flag

### Practical rule

Do not ask this family to do too much at first.

It is already useful if it prevents bad longs.

That is enough for first deployment.


---

## Context Consumption Rule

When consuming strategy/context state from strategy_signal_context, prefer an as-of join:

- latest context_ts_utc
- for same asset_id and interval_code
- where context_ts_utc <= target anchor timestamp

Do not assume exact timestamp equality unless the pipeline guarantees alignment.

This was confirmed during FAILED_BREAKOUT_4H_V1 overlay integration.

### Example

For selection/advice overlays, the correct anchor is typically:
- selection_state.advice_ts_4h_utc

not always:
- selection_state.asof_ts_utc

This distinction matters because context state may be published on the latest valid 4h anchor prior to the current selection snapshot.

