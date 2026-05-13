# Breath Curve Phase Calibration Findings — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Record findings from fine-offset Breath Curve phase calibration v2.

The fine-offset run used:

- offset grid: -10.5 to +10.5
- step: 0.5 day
- checkpoints: 0.618 and 0.786
- symbols: BTC, ETH, TAO, RENDER, FIL, HBAR, XLM, PEPE
- anchors: 2026-03-01, 2026-03-22, 2026-04-12

## Core finding

Exact offset-match is too brittle as a primary phase-quality metric, especially for 0.618.

For 0.618, the selected partial offset often detects early structure, while the best full-cycle offset may resolve into a different harmonic band.

Therefore:

    0.618 selected offset = early recognition lens
    best full offset = later realized cycle geometry
    distance between them = phase drift / expansion path

## 0.618 recognition behavior

Fine-offset 0.618 summary:

- average return to 1.000: 6.1372%
- positive return rate to 1.000: 87.50%
- exact offset-match rate: 8.33%

The strongest selected recognition band was around -7:

| checkpoint | selected band | rows | avg return to 1.000 | positive to 1.000 | avg return to 1.272 |
|---|---:|---:|---:|---:|---:|
| 0.618 | -7 | 9 | 9.5446 | 100.00% | 6.1582 |

Interpretation:

0.618 selected -7/-8 appears to detect early/forming structure better than exact zero-offset matching.

## 0.618 offset distance

0.618 outcomes were not strongest when exact offset-match occurred.

| distance bucket | rows | avg return to 1.000 | avg return to 1.272 | positive to 1.272 |
|---|---:|---:|---:|---:|
| exact / near | 2 | -0.9441 | 1.3630 | 50.00% |
| within 0.5d | 3 | 9.9240 | 10.2385 | 66.67% |
| within 1d | 1 | 3.8106 | 15.6354 | 100.00% |
| far | 15 | 6.1353 | 10.5649 | 80.00% |

Interpretation:

For 0.618, phase drift is not automatically bad. Constructive drift may be part of the recognized cycle maturing into a different full-cycle geometry.

## 0.786 ignition behavior

0.786 behaves differently from 0.618.

Fine-offset 0.786 summary:

- average return to 1.000: 1.9732%
- positive return rate to 1.000: 70.83%
- exact offset-match rate: 29.17%

At 0.786, exact/near offset-match was materially better:

| distance bucket | rows | avg return to 1.000 | avg return to 1.272 | positive to 1.272 |
|---|---:|---:|---:|---:|
| exact / near | 7 | 5.1670 | 13.5315 | 100.00% |
| far | 15 | -0.2269 | 3.6601 | 60.00% |

Band-match at 0.786 also performed better than non-match:

| band width | match state | rows | avg return to 1.000 | avg return to 1.272 | positive to 1.272 |
|---|---|---:|---:|---:|---:|
| 1.0d | MATCH | 6 | 6.0125 | 15.2237 | 100.00% |
| 1.0d | NO_MATCH | 18 | 0.6268 | 3.9777 | 61.11% |
| 1.5d | MATCH | 8 | 6.3182 | 14.6662 | 100.00% |
| 1.5d | NO_MATCH | 16 | -0.1992 | 2.8507 | 56.25% |

Interpretation:

0.786 is not a broad recognition gate, but when phase/band coherence is present, it becomes useful as an ignition or overflow confirmation filter.

## Best full-band behavior

0.618 best-full extension bands:

| checkpoint | best full band | rows | avg return to 1.272 | positive to 1.272 |
|---|---|---:|---:|---:|
| 0.618 | +0 | 5 | 12.8289 | 100.00% |
| 0.618 | +3 | 3 | 11.9271 | 100.00% |
| 0.618 | +7 | 2 | 22.7722 | 100.00% |

0.786 best-full extension bands:

| checkpoint | best full band | rows | avg return to 1.272 | positive to 1.272 |
|---|---|---:|---:|---:|
| 0.786 | +0 | 5 | 10.5813 | 100.00% |
| 0.786 | +7 | 2 | 30.2604 | 100.00% |

Interpretation:

- +0 / +3 best-full bands look like clean continuation.
- +7 best-full band looks like extension / overflow path.
- +9 / +10.5 remain late/stretch candidates and need more data before use.

## Updated research thesis

Previous:

    offset_match = risk quality filter

Refined:

    0.618 exact offset-match is too brittle.
    0.618 phase drift can be constructive.
    0.786 exact/band match is meaningful as ignition/overflow confirmation.
    band and distance metrics are more useful than exact offset equality.

## Working phase model

Current model:

    0.618 selected -7/-8 = early measured recognition / forming structure
    0.618 selected 0 = clean/tight recognition, sample-thin but high-quality
    0.786 exact/band-match = ignition coherence / extension confirmation
    best-full +0/+3 = clean continuation
    best-full +7 = extension / overflow path
    best-full +9/+10.5 = late stretch / unreliable drift candidate

## Next validation

1. Add band/distance metrics to policy backtest outputs.
2. Re-run random-anchor baselines using:
   - 0.618 selected -7/-8
   - 0.786 band-match 1.0d or 1.5d
   - best-full +7 extension candidate
3. Compare against same-symbol same-regime random anchors.
4. Extend to 4h timing validation only after daily band calibration is stable.

## Boundary

These findings are not strategy rules.

Forbidden downstream use:

- selection_engine modifier
- decision_gate rule
- execution_planner instruction
- executor/order logic
- live or paper execution trigger
