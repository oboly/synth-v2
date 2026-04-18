# Failed Breakout Deployment Plan

## Family
- FAILED_BREAKOUT_4H_V1

## Status
- KEEP / PRIORITY

## Current evidence
Recent-window testing showed materially negative next 4h forward return after failed upside breakout structure.

This is strong enough to treat the family as real and useful.

## Recommended role order

### 1. Risk Overlay / Avoid-Long
First role:
- block or downgrade fresh breakout longs
- prevent breakout chasing in failure context

Why:
- immediate value
- low deployment risk
- no short execution stack required yet

### 2. Bearish Context State
Second role:
- explicit bearish structural context in interpreter/state layer
- visible to advice, ranking, and risk layers

Why:
- family expresses context, not only entry
- good fit for modular architecture

### 3. Short Candidate Family
Later role:
- dedicated bearish entry family
- requires further testing:
  - horizon extension
  - execution realism
  - short-side assumptions
  - risk controls

## Recommended landing point

### Best first landing
- interpreter_state
or
- strategy_signal_context

### Why
These layers are intended to hold contextual market meaning without forcing execution directly.

## Proposed initial semantics

Failed upside breakout means:
- breakout continuation thesis weakened
- bullish continuation quality reduced
- short-term downside risk elevated

## Proposed initial outputs

Potential outputs later:
- failed_breakout_flag_4h
- breakout_failure_state = FAILED_UPSIDE_BREAKOUT
- bearish_failure_context_score
- avoid_long_overlay_flag = 1

## Advice / ranking implications

Possible first effects:
- lower long confidence
- lower breakout continuation score
- raise avoid-long bias
- raise bearish context score

## Risk implications

Possible first effects:
- smaller target fraction for fresh longs
- stricter invalidation tolerance on breakout-style longs
- no breakout-chase entries while flag is active

## Final principle

Do not force this family into direct short execution too early.

Its first job is to stop bad longs and improve context.

That is already valuable enough.


---

## Initial Overlay Heuristic

### Current first-use rule

If:
- failed_breakout_flag_4h = 1
- avoid_long_overlay_flag = 1
- selection_bias IN ('BULLISH', 'LONG', 'BUY', 'LONG_BIAS')

Then:
- selection_score_after_overlay = selection_score - 0.10

Otherwise:
- selection_score_after_overlay = selection_score

### Purpose

This is a first defensive overlay only.

It is intended to:
- reduce breakout-chasing behavior
- downgrade bullish candidates in failed breakout context
- expose bearish structural failure without forcing direct short execution

### Current scope

This heuristic is intentionally:
- small
- explicit
- reversible
- easy to inspect

It is not yet:
- a hard block
- a risk-engine rule
- an execution-layer rule

### Current interpretation

FAILED_BREAKOUT_4H_V1 is currently used as:

- avoid-long overlay
- bearish structural context modifier
- anti-FOMO filter

### Validation status

Current check confirmed:
- overlay is active through strategy_signal_context
- as-of join semantics are required for context consumption
- bullish/long-bias rows can be downgraded correctly

### Future refinement options

Possible later refinements:
- scale penalty by bearish_failure_context_score
- apply only to breakout-style bullish states
- separate visual warning from score penalty
- promote into advice/risk semantics more explicitly

