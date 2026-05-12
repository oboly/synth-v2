# Breath Curve Policy Baseline Findings — 2026-05-12

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Record the first DB-backed Breath Curve policy baseline comparison findings after adding same-window baseline reporting and offset-match-only research runs.

## Runs

Latest relevant DB runs:

| run_id | policy | checkpoint | offset required | rows | avg policy return | positive rate |
|---:|---|---:|---:|---:|---:|---:|
| 2 | breath_curve_research_policy_0618_v1 | 0.618 | 0 | 24 | 6.8411 | 91.67% |
| 3 | breath_curve_research_policy_0786_extension_v1 | 0.786 | 0 | 24 | 4.3659 | 58.33% |
| 4 | breath_curve_research_policy_0618_offset_match_v1 | 0.618 | 1 | 10 | 7.2331 | 100.00% |
| 5 | breath_curve_research_policy_0786_offset_match_v1 | 0.786 | 1 | 5 | 8.0743 | 80.00% |

## Findings

### 0.618 checkpoint

The 0.618 checkpoint remains the cleaner early-recognition lane.

Baseline comparison:

- non-offset-filtered 0.618 policy average: 6.8411
- offset-match-only 0.618 policy average: 7.2331
- offset-match-only 0.618 positive rate: 100.00%
- offset-match-only 0.618 worst return: +1.8972%

Interpretation:

0.618 plus offset-match is currently the cleanest candidate research filter.

### 0.786 checkpoint

The 0.786 checkpoint behaves more like an extension / overshoot detector.

Baseline comparison:

- non-offset-filtered 0.786 policy average: 4.3659
- offset-match-only 0.786 policy average: 8.0743
- offset-match-only 0.786 positive rate: 80.00%
- offset-match-only 0.786 worst return: -4.7366%

Interpretation:

0.786 plus offset-match may identify stronger extension candidates, but sample size is thinner and risk remains higher.

### Offset-match quality

Offset-match remains a strong quality discriminator.

Combined latest baseline:

- offset_match=1 average: 7.6401
- offset_match=1 positive rate: 93.33%
- offset_match=0 average: 4.6202
- offset_match=0 positive rate: 66.67%

Interpretation:

Offset-match is a serious research-quality filter candidate, but must remain research-only until tested against broader history and random-anchor baselines.

## Symbol buckets

Current strongest policy buckets:

| symbol | rows | avg policy return | positive rate |
|---|---:|---:|---:|
| TAO | 9 | 13.6228 | 88.89% |
| PEPE | 6 | 7.4102 | 83.33% |
| FIL | 8 | 6.7766 | 75.00% |
| RENDER | 10 | 6.3008 | 80.00% |

Interpretation:

- TAO currently shows the strongest return profile.
- RENDER remains cleaner and better represented than most.
- FIL and PEPE show stronger speculative / overshoot behavior and should not be treated as clean structural filters yet.

## Boundary

These findings are not strategy rules.

Forbidden downstream use:

- selection_engine modifier
- decision_gate rule
- execution_planner instruction
- executor/order logic
- live or paper execution trigger

Correct next validation steps:

1. Random-anchor baseline using candle resampling.
2. Same-symbol random anchor comparison.
3. Regime bucket comparison.
4. 4h partial-cycle extension later.
5. Only after validation: consider whether a market-only feature belongs upstream of selection_engine.
