# A+ Harmonic Snapshot Validation Findings — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Record first validation results for the A+ harmonic phase snapshot against real Breath Curve policy rows and same-symbol random-anchor baselines.

## Core finding

A+ harmonic labels are not validated as standalone alpha.

They are more useful as:

- coherence labels
- progression-state labels
- downside/risk-quality labels
- research buckets for future transition validation

## Clean 0.618 confirmed bucket

A+ clean 0.618 confirmed did not beat random on broad 0.618 average return:

| bucket | real avg | random avg | real minus random |
|---|---:|---:|---:|
| APLUS_CLEAN_0618_CONFIRMED / 0618_all | 2.9620 | 2.9959 | -0.0339 |

But it improved when combined with measured offset-match:

| bucket | real avg | random avg | real minus random | real positive | random positive | real worst | random worst |
|---|---:|---:|---:|---:|---:|---:|---:|
| APLUS_CLEAN_0618_CONFIRMED / 0618_offset_match | 3.4676 | 2.1389 | 1.3287 | 100.00% | 62.90% | 1.8972 | -17.6505 |

Interpretation:

A+ clean 0.618 plus measured offset-match behaves as a quality/downside filter, not pure alpha.

## Forming early bucket

The strongest directional result came from A+ forming/early labels combined with measured 0.618:

| bucket | real avg | random avg | real minus random | real positive | real worst | random worst |
|---|---:|---:|---:|---:|---:|---:|
| APLUS_FORMING_EARLY / 0618_all | 5.5264 | 3.3503 | 2.1761 | 100.00% | 1.7111 | -23.4311 |

Interpretation:

A+ early/forming states may be useful if later confirmed by measured 0.618 structure.

This suggests transition validation may be more important than static snapshot validation.

## Clean late extension bucket

A+ clean late extension showed strong 0.618 average return, but sample size is tiny:

| bucket | real rows | real avg | random avg | real minus random |
|---|---:|---:|---:|---:|
| APLUS_CLEAN_LATE_EXTENSION / 0618_all | 3 | 15.1225 | 9.0573 | 6.0652 |

Interpretation:

Interesting, but not proven. Treat as extension/exhaustion research, not recognition.

## 0.786

0.786 remains weak as a recognition lane.

Across most A+ buckets, 0.786 variants underperformed same-symbol random anchors or had tiny real sample counts.

Interpretation:

0.786 should remain an overflow/extension diagnostic, not a primary timing gate.

## Updated thesis

Current best interpretation:

- A+ clean 0.618 = coherence label
- measured offset-match = downside/risk-quality filter
- A+ forming early + later measured 0.618 = possible progression edge
- A+ late extension = potentially strong but late and sample-thin
- 0.786 = overflow diagnostic, not broad entry/recognition
- transition validation matters more than static snapshot validation

## Next validation

Build A+ transition validation across multiple snapshots:

- early/forming -> confirmed 0.618
- confirmed 0.618 -> 0.786 building/active
- 0.786 active -> 1.000 / 1.272 extension
- clean -> dirty drift
- offset band convergence toward 0/+3
- offset band drift toward +5/+7/+10.5

## Boundary

These findings are not strategy rules.

Forbidden downstream use:

- selection_engine modifier
- decision_gate rule
- execution_planner instruction
- executor/order logic
- live or paper execution trigger
