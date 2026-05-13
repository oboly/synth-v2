# Breath Curve Random-Anchor Wider-Window Findings — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Record wider-window same-symbol random-anchor baseline v2 results.

This tests whether prior Breath Curve policy outcomes outperform same-symbol random anchors over a broader sampled anchor window.

## Run

Runner:

    python -m src.research.run_breath_curve_random_anchor_baseline_v2 \
      --start-date 2025-12-01 \
      --end-date 2026-04-03 \
      --samples-per-symbol 250 \
      --seed 260512 \
      --exclude-real-anchor-days 3 \
      --output none

Actual sampled anchors:

- 8 symbols
- 107 random anchors per symbol
- 856 random candidates per checkpoint bucket
- same-symbol only
- known real anchors excluded by +/- 3 days
- full-cycle coverage required

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

| bucket | real rows | random candidates | random eligible | random selection rate | real avg | random avg | real minus random | real positive | random positive | real worst | random worst |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0618_all | 24 | 856 | 856 | 100.0000% | 6.8411 | 6.0607 | 0.7804 | 91.6667% | 69.6262% | -2.9005 | -23.4311 |
| 0618_offset_match | 10 | 856 | 265 | 30.9579% | 7.2331 | 9.0450 | -1.8119 | 100.0000% | 72.4528% | 1.89725 | -23.4311 |
| 0786_all | 24 | 856 | 828 | 96.7290% | 4.3659 | 6.8853 | -2.5194 | 58.3333% | 74.8792% | -19.900875 | -22.1918 |
| 0786_offset_match | 5 | 856 | 175 | 20.4439% | 8.0743 | 11.0145 | -2.9402 | 80.0000% | 85.7143% | -4.73665 | -16.0697 |

## Findings

### 0.618 all

0.618 all continues to beat same-symbol random anchors, but the average-return edge is modest in the wider window.

- real average: 6.8411
- random average: 6.0607
- real minus random: +0.7804
- real positive rate: 91.6667%
- random positive rate: 69.6262%
- real worst: -2.9005
- random worst: -23.4311

Interpretation:

0.618 all shows a modest timing edge and a much stronger downside-quality advantage versus random anchors.

### 0.618 offset_match

0.618 + offset_match does not beat random offset_match on average return in the wider window.

- real average: 7.2331
- random average: 9.0450
- real minus random: -1.8119

However, it remains much cleaner on consistency and downside:

- real positive rate: 100.0000%
- random positive rate: 72.4528%
- real worst: +1.89725
- random worst: -23.4311

Interpretation:

0.618 + offset_match currently behaves more like a risk-quality / downside-control filter than a pure average-return alpha filter.

### 0.786 all

0.786 all underperforms random anchors.

- real average: 4.3659
- random average: 6.8853
- real minus random: -2.5194
- real positive rate: 58.3333%
- random positive rate: 74.8792%

Interpretation:

0.786 all is not validated as a broad timing/recognition lane.

### 0.786 offset_match

0.786 + offset_match also underperforms random offset-match candidates on average return.

- real average: 8.0743
- random average: 11.0145
- real minus random: -2.9402

Interpretation:

0.786 remains useful as an extension/overshoot research lens, but not as a validated edge lane.

## Updated research thesis

Current best-supported interpretation:

    Breath Curve 0.618 = modest timing edge + strong downside filter
    Offset-match = consistency / risk-quality filter, not alpha by itself
    0.786 = extension/overshoot lens, not primary recognition logic

## Symbol observations

Random-anchor averages are especially high for RENDER, TAO, and PEPE in offset-match buckets.

This means high random performance may partly reflect symbol/regime momentum rather than Breath Curve-specific edge.

Important implication:

    Future validation must compare against symbol/regime buckets,
    not just global random anchors.

## Boundary

These findings are not strategy rules.

Forbidden downstream use:

- selection_engine modifier
- decision_gate rule
- execution_planner instruction
- executor/order logic
- live or paper execution trigger

## Next validation steps

1. Add risk metrics to random-anchor baseline:
   - standard deviation
   - median
   - 25th percentile
   - 10th percentile
   - downside tail
2. Add regime bucket joins.
3. Compare same-symbol same-regime random anchors.
4. Re-run using additional anchor windows.
5. Only after validation consider a market-only research feature proposal.
