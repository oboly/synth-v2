# Reversion State Score

## Purpose

This document defines the current working interpretation of the `rejected_htf_4h` edge.

Main conclusion:

`rejected_htf_4h` is not the primitive edge.

It is currently best understood as a proxy for a low-conviction downside extension below EMA20 that tends to mean-revert on the next 4h horizon.

---

## Core Finding

The edge did not validate as:
- liquidity sweep
- reclaim event
- wick reversal event
- panic flush reversal

The edge did validate as:
- recent downside extension present
- price below EMA20
- continuation participation weak or normal
- high-volume downside continuation degrades performance

This is best described as:

low-conviction downside continuation failure

or:

sub-EMA exhaustion bounce without strong distribution

---

## Empirical Evidence

### Score bucket result

Observed result for `rejected_htf_4h`:

| Score Bucket | N  | Avg Trade Return |
|-------------|---:|-----------------:|
| LOW         | 14 | -0.000729788571  |
| MID         | 20 |  0.000811989000  |
| HIGH        | 23 |  0.005788020435  |
| VERY_HIGH   |  3 |  0.003270540000  |

Interpretation:
- LOW bucket is negative
- MID bucket is slightly positive
- HIGH bucket is clearly strongest
- VERY_HIGH remains positive but sample is too small to dominate interpretation

This supports the claim that the usable primitive is the score, not the legacy label.

---

## Additional Behavior

### Volume behavior

For `rejected_htf_4h` within shallow 24h downside:
- HIGH_VOLUME underperformed
- LOW_VOLUME performed better
- NORMAL_VOLUME performed best

Interpretation:

The edge is stronger when the downside move lacks strong participatory conviction.

### EMA20 behavior

For `rejected_htf_4h`:
- BELOW_EMA20 + LOW_VOLUME performed strongly
- BELOW_EMA20 + NORMAL_VOLUME performed strongly
- DEEP_BELOW_EMA20 + HIGH_VOLUME degraded sharply
- NEAR_OR_ABOVE_EMA20 lost the edge

Interpretation:

The setup needs downside stretch below short-term mean, but not panic-quality sell pressure.

---

## Working Mechanism

The current best explanation is:

1. Price drifts lower over the recent 4h and 24h horizon
2. Price sits below EMA20
3. Participation is weak or only normal
4. Continuation quality is poor
5. The next 4h period mean-reverts upward

This is not a dramatic reversal story.

It is a quieter market mechanics story:

the market looks weak, but the weakness is not strong enough to continue efficiently

---

## Reversion State Score

### Current score logic

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

### Bucket interpretation

- LOW: score <= 1
- MID: score 2-3
- HIGH: score 4-5
- VERY_HIGH: score >= 6

### Current interpretation of buckets

- LOW = avoid / weak bounce context
- MID = weak positive context
- HIGH = strongest current bounce context
- VERY_HIGH = interesting but currently undersampled

---

## Architectural Implication

The system should move from:

`rejected_htf_4h` as primary explanation

to:

`reversion_state_score` as primary explanation

Therefore:
- `rejected_htf_4h` should remain usable as a legacy comparison policy
- but the mechanism should live in state logic, not label logic

---

## Recommended Implementation Direction

### Near-term

- keep `rejected_htf_4h` for comparison and validation
- maintain `v_reversion_state_backtest`
- maintain diagnostic scripts against the view

### Next implementation target

Add to state layer:
- `reversion_state_score`
- `reversion_state_bucket`

Target home:
- `signal_engine_state`
- or a closely related state/interpreter layer if preferred

### Not recommended yet

- removing event tables
- deleting `rejected_htf_4h`
- forcing production logic replacement before broader validation

---

## What this edge is NOT

It is not primarily:
- wick rejection alpha
- sweep/reclaim alpha
- capitulation reversal alpha
- panic flush alpha

Those ideas were tested and did not explain the observed trades.

---

## Legacy Policy Repositioning

`rejected_htf_4h` should be treated as:
- a useful legacy policy
- a proxy label
- a benchmark for comparison

It should not be treated as the ground-truth market mechanic.

Ground-truth mechanic currently appears to be:

reversion after low-conviction downside extension below EMA20

---

## Next Validation Tasks

1. Test the same score logic on `rejected_htf_top10_4h`
2. Compare score buckets directly across:
   - rejected_htf_4h
   - rejected_htf_top10_4h
   - strong_candidate_4h
   - watch_4h
3. Test whether EMA50 adds real lift or only noise
4. Test whether VERY_HIGH remains valid on larger sample
5. Move score from backtest-only logic into state architecture
