# Failed Breakout - Next Steps

## Current status

Pattern family:
- FAILED_BREAKOUT_4H_V1

Verdict:
- KEEP / PRIORITY

## Why it matters

Recent-window result showed:
- count: 389
- avg next_return_4h: -0.020247
- median next_return_4h: -0.018464

This is a meaningful bearish post-failure family.

## Current interpretation

This family is currently better understood as:
- avoid-long signal
- reversal / short-context family
- risk overlay against breakout chasing

Not a long-entry family.

## Next tests

1. FAILED_BREAKOUT_4H_V2
   - refine breakout lookback window
   - refine failure timing window

2. Horizon extension
   - next_return_8h
   - next_return_1d later

3. Universe split
   - larger/liquid assets
   - broader alt universe

4. Context split
   - momentum regime
   - reversion regime
   - higher timeframe alignment later

5. Product role decision
   - avoid-long only
   - short candidate
   - both


---

## Deployment Plan

### First deployment role
- risk overlay
- avoid-long family
- bearish context state

### Not first deployment role
- direct short execution family

### Reason
The family already has clear negative forward-return behavior after failed upside breakout.
That is enough to make it useful as a defensive or bearish context component before short execution is researched further.

### First integration target
Prefer later landing in:
- interpreter_state
or
- strategy_signal_context

### First-use behaviors
- downgrade bullish breakout setups
- reduce breakout-chasing confidence
- mark avoid-long context
- raise bearish structural context

