# Review Request: Reversion State Score vs rejected_htf_4h

## Context

We ran a backtest on a crypto strategy label called `rejected_htf_4h`.

Initial intuition was that the edge might come from:
- liquidity sweep
- failed breakdown
- wick rejection
- short squeeze
- relief rally

Those ideas were tested and did not hold up as the primary explanation.

Current best interpretation:

`rejected_htf_4h` appears to be a proxy for a **low-conviction downside extension below EMA20** that tends to mean-revert upward on the next 4h horizon.

---

## What was tested

### Rejection / liquidity event hypothesis
Joined trades to:
- `feat_rejection_event`
- `feat_liquidity_event`

Result:
- these event tables did not explain the trades
- no convincing sweep/reclaim mechanism was found for this trade set

### Wick reversal hypothesis
Tested wick-related context.

Result:
- wick reversal did not explain the edge
- all observed trades effectively fell into low wick reversal context

### Context / feature hypothesis
Joined trades to `feat_candle` context.

Observed pattern:
- edge improved below EMA20
- edge weakened when price was near/above EMA20
- edge weakened under high-volume downside continuation
- edge improved under low or normal participation

Interpretation:
- not dramatic reversal
- more like weak bearish continuation that fails to keep pushing

---

## Current score logic

Working score:

score = 0

if price_vs_ema20 <= -0.005: +2
if price_vs_ema20 <= -0.020: +1

if price_vs_ema50 <= -0.010: +1
if price_vs_ema50 <= -0.030: +1

if ret_4h < 0: +1
if ret_24h < 0: +1

if volume_ratio_20 < 1.10: +1
if volume_ratio_20 > 1.10: -2

if volume_zscore_20 > 0.50: -1

Bucket interpretation:
- LOW: score <= 1
- MID: score 2-3
- HIGH: score 4-5
- VERY_HIGH: score >= 6

---

## Main empirical result

Observed result for `rejected_htf_4h`:

| Score Bucket | N  | Avg Trade Return |
|-------------|---:|-----------------:|
| LOW         | 14 | -0.000729788571  |
| MID         | 20 |  0.000811989000  |
| HIGH        | 23 |  0.005788020435  |
| VERY_HIGH   |  3 |  0.003270540000  |

Interpretation:
- LOW is negative
- MID is slightly positive
- HIGH is clearly strongest
- VERY_HIGH remains positive but has very small sample

---

## Important limitation

Multi-policy validation is NOT yet confirmed.

At the moment, the comparison dataset only contains:
- `rejected_htf_4h`

So the current conclusion is:

- `reversion_state_score` looks stronger than the legacy label **inside this policy**
- but it is NOT yet proven as a general primitive across other policies

---

## Current working conclusion

The best current explanation is:

This is not a sweep/reclaim alpha and not a wick-rejection alpha.

It is more likely a **low-conviction downside continuation failure**:
- price drifts below EMA20
- recent returns are weak
- participation is weak or normal
- continuation quality is poor
- next 4h mean-reverts upward

---

## What I want reviewed

Please review this as a system designer / quant / trader.

I want critique on:

1. Is the mechanism interpretation logically sound?
2. Is the score design direction reasonable, or is it overfit / misframed?
3. What alternative mechanism explanations still fit the evidence?
4. What are the biggest blind spots in this reasoning?
5. What exact next tests would you run before integrating this into a signal engine?

Please be critical and precise.
