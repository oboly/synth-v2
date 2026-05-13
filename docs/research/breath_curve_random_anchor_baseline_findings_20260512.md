# Breath Curve Random-Anchor Baseline Findings — 2026-05-12

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Record the first deterministic same-symbol random-anchor baseline v2 results.

The key research question:

Does 0.618 + offset_match beat same-symbol random anchors?

## Run

Runner:

    python -m src.research.run_breath_curve_random_anchor_baseline_v2 \
      --start-date 2026-03-01 \
      --end-date 2026-04-12 \
      --samples-per-symbol 100 \
      --seed 260512 \
      --output table

Actual sampled anchors:

- 8 symbols
- 19 random anchors per symbol
- 152 random candidates per checkpoint bucket
- reason: same tested date window plus full-cycle coverage constraints limited valid anchor candidates

Symbols:

- BTC
- ETH
- TAO
- RENDER
- FIL
- HBAR
- XLM
- PEPE

## Core comparison

| bucket | real rows | random candidates | random eligible | real avg | random avg | real minus random | real positive | random positive | real worst | random worst |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0618_all | 24 | 152 | 152 | 6.8411 | 4.8237 | 2.0174 | 91.67% | 74.34% | -2.9005 | -20.4030 |
| 0618_offset_match | 10 | 152 | 49 | 7.2331 | 7.7419 | -0.5088 | 100.00% | 75.51% | 1.8972 | -7.2002 |
| 0786_all | 24 | 152 | 151 | 4.3659 | 6.1726 | -1.8067 | 58.33% | 82.12% | -19.9009 | -4.5362 |
| 0786_offset_match | 5 | 152 | 31 | 8.0743 | 9.1597 | -1.0854 | 80.00% | 93.55% | -4.7366 | -4.3707 |

## Findings

### 0.618 all

0.618 all beats same-symbol random anchors on average return and downside.

- real average: 6.8411
- random average: 4.8237
- real minus random: +2.0174
- real worst: -2.9005
- random worst: -20.4030

Interpretation:

The broad 0.618 lane shows real edge versus same-symbol random anchors in this first sample.

### 0.618 offset_match

0.618 + offset_match does not beat random offset_match on average return in this first sample.

- real average: 7.2331
- random average: 7.7419
- real minus random: -0.5088

But it has much cleaner risk behavior:

- real positive rate: 100.00%
- random positive rate: 75.51%
- real worst: +1.8972
- random worst: -7.2002

Interpretation:

0.618 + offset_match currently looks more like a risk-quality filter than a pure average-return alpha filter.

### 0.786 all

0.786 all underperforms same-symbol random anchors.

- real average: 4.3659
- random average: 6.1726
- real minus random: -1.8067
- real positive rate: 58.33%
- random positive rate: 82.12%

Interpretation:

0.786 all is not validated as a broad recognition lane.

### 0.786 offset_match

0.786 + offset_match also underperforms random offset_match on average return.

- real average: 8.0743
- random average: 9.1597
- real minus random: -1.0854

Interpretation:

0.786 offset_match remains interesting as an extension bucket, but this first random-anchor baseline does not validate it as superior to random same-symbol offset-match candidates.

## Current answer

Does 0.618 + offset_match beat same-symbol random anchors?

Current answer:

    No on average return.
    Yes on downside/consistency.
    Needs broader-window validation.

## Important limitation

The tested window only yielded 19 random anchors per symbol after excluding anchors too close to real anchors and requiring full-cycle coverage.

This is enough for a first sanity check, but not enough for final validation.

## Next validation steps

1. Run wider-window random-anchor baseline.
2. Run same-symbol per-regime random baseline.
3. Compare against 0.618 all and 0.618 offset_match separately.
4. Add quantiles, standard deviation, and drawdown-style risk metrics.
5. Only after broader validation consider whether any market-only feature belongs upstream of selection_engine.

## Boundary

These findings are not strategy rules.

Forbidden downstream use:

- selection_engine modifier
- decision_gate rule
- execution_planner instruction
- executor/order logic
- live or paper execution trigger
