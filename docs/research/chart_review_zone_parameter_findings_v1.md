# Chart Review Zone Parameter Findings V1

## Purpose

This document captures human visual findings from the first lifecycle and chart
review pass.

It exists to:

- record what looked directionally useful in early chart review
- separate zone-detection quality from zone-interpretation quality
- guide future parameter calibration work
- preserve findings before later calibration and replay lanes expand

This document does not introduce code changes or runtime changes.

## High-Level Finding

Zones often look visually plausible.

The main issue does not appear to be only:

- whether a zone exists

but more importantly:

- how that zone is interpreted
- when it is treated as support
- when it is treated as reaction
- when it is treated as continuation
- when it is treated as exhaustion

The practical problem is interpretation, not just detection.

## First Visual Findings

Observed findings from the first chart/cockpit review:

- zones are often directionally useful
- the same visual zone can imply different behavior depending on market context
- local TP can be too early if it is treated as the main TP
- fib extension ladder should distinguish local reaction from real extension
  targets
- reload zones after spike behavior can look promising
- coin-specific behavior likely matters
- coin group / sector behavior likely matters
- regime likely changes whether a zone behaves as support, reaction, or failure
- breath / phase likely changes whether continuation or exhaustion is more
  likely

This means a one-size-fits-all interpretation is likely too weak.

## Zone Interpretation Findings

Important distinction:

- a zone can be visually correct
- the default parameter interpretation can still be wrong

Examples of interpretation drift:

- local reaction target treated as the main TP
- reload-worthy pullback treated as passive hold
- continuation context treated as exhaustion too early
- exhaustion context treated as reload too aggressively

The implication is that calibration must target interpretation rules, not just
zone geometry.

## Fibo Interaction

Fibo is treated as the natural price-growth and target structure.

Implications:

- local TP should remain visible
- local TP should not automatically be treated as the main bull objective
- fib extension ladder should separate:
  - local reaction TP
  - `1.272`
  - `1.618`
  - `2.618`
  - `3.618`
  - `4.236`

The chart review suggests:

- local TP often works as a reaction marker
- larger fib extension targets can describe the broader curve better
- fib target status should influence whether trim, hold, or reload interpretation
  is favored

## Coin Identity And Group Effects

Visual review suggests behavior may stay relatively consistent through time, but
that consistency is shaped by:

- coin identity
- coin group / sector
- liquidity class
- volatility character
- regime
- breath / phase
- fib target ladder status

This suggests future calibration should not assume one universal parameter set
for all coins.

## Parameter Families To Calibrate Later

Later calibration lanes should consider at least:

- `near_zone_threshold_pct`
- `near_target_threshold_pct`
- `reclaim_confirm_threshold`
- `reload_distance_pct`
- `intrabar_touch_fresh_minutes`
- `fib_target_preference`
- `trim_size_hint`
- `hold_vs_takeprofit_bias`

These should be treated as calibration families, not fixed truths.

## Proposed Calibration Dimensions

Later calibration should be segmented by:

- symbol
- coin group / sector
- liquidity class
- volatility bucket
- regime
- breath phase
- fib target status
- anchor quality

This is important because the same numeric threshold may be too loose for one
coin class and too tight for another.

## Practical Interpretation Direction

Early working interpretation:

- zone detection is often good enough to be useful
- local TP should be treated as a local reaction reference, not always the final
  take-profit map
- fib extension ladder should help decide whether price is merely reacting or
  still unfolding into a larger target structure
- reload logic deserves more attention after spikes and partial profit-taking
- breath and regime should later help decide whether the same zone is more
  likely to mean support, continuation, or exhaustion

## Strategy Validation Rule

Global rule for all future strategy validation:

- every strategy must compare against `HOLD` / buy-and-hold baseline
- report excess return versus `HOLD`
- report drawdown improvement versus `HOLD`
- profit alone is not sufficient

This applies even if a zone-driven or fib-driven strategy looks profitable in
absolute terms.

Absolute profit is not enough.
The relevant question is whether the strategy improves on passive hold after
considering both return and drawdown.

## Boundaries

This document is:

- research-only
- interpretive
- non-executable

It does not imply:

- execution
- paper trading
- live trading
- `selection_engine` changes
- `decision_gate` changes
- runtime parameter changes

The next step is calibration research, not promotion into live logic.

## Summary

Current visual review suggests:

- zones often make directional sense
- interpretation is the larger problem
- local TP is often too early when treated as the main TP
- fib extension ladder should frame larger target identity
- reload zones after spikes deserve focused study
- calibration likely needs segmentation by coin identity, group, liquidity,
  regime, breath, fib target status, and anchor quality
- every later strategy result must be compared against `HOLD` / buy-and-hold
  baseline before it can be treated as meaningful
