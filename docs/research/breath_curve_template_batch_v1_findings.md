# Breath Curve Template Batch v1 Findings

Status: research-only  
Scope: market-only / account-agnostic  
Downstream use: undefined until historical validation  

## Purpose

Record the first multi-anchor batch run for the A+ 21-day Breathline Curve Template Matcher.

The matcher only measures waveform alignment and pivot-match quality. It does not define selection, risk, or execution behavior.

## Batch setup

Symbols:

    BTC, ETH, TAO, RENDER, FIL, HBAR, XLM, PEPE

Anchors:

    2026-03-01
    2026-03-22
    2026-04-12

Cycle:

    21 days

Offset grid:

    -10.5, -7, -5, -3, 0, +3, +5, +7, +10.5

Tolerance:

    36 hours

## Compact ranking by score

| Rank | Symbol | Anchor | Offset | Score | Shape | Timing |
|---:|---|---|---:|---:|---:|---:|
| 1 | BTC | 2026-04-12 | 0.0 | 0.9097 | 1.0000 | 0.7743 |
| 2 | RENDER | 2026-04-12 | 0.0 | 0.8716 | 1.0000 | 0.6791 |
| 3 | ETH | 2026-03-22 | 5.0 | 0.8572 | 1.0000 | 0.6429 |
| 4 | PEPE | 2026-03-22 | 5.0 | 0.8572 | 1.0000 | 0.6429 |
| 5 | BTC | 2026-03-22 | 5.0 | 0.8555 | 1.0000 | 0.6387 |
| 6 | RENDER | 2026-03-22 | -7.0 | 0.8335 | 1.0000 | 0.5838 |
| 7 | FIL | 2026-03-22 | 3.0 | 0.8335 | 1.0000 | 0.5838 |
| 8 | PEPE | 2026-04-12 | 7.0 | 0.8271 | 1.0000 | 0.5678 |
| 9 | TAO | 2026-04-12 | 0.0 | 0.8190 | 1.0000 | 0.5476 |
| 10 | RENDER | 2026-03-01 | -5.0 | 0.7971 | 1.0000 | 0.4928 |
| 11 | ETH | 2026-04-12 | 0.0 | 0.7966 | 0.8750 | 0.6791 |
| 12 | FIL | 2026-04-12 | 7.0 | 0.7890 | 1.0000 | 0.4726 |
| 13 | TAO | 2026-03-01 | -7.0 | 0.7826 | 1.0000 | 0.4566 |
| 14 | BTC | 2026-03-01 | -7.0 | 0.7822 | 1.0000 | 0.4554 |
| 15 | XLM | 2026-03-01 | 3.0 | 0.7788 | 1.0000 | 0.4471 |
| 16 | HBAR | 2026-03-22 | 3.0 | 0.7581 | 0.8750 | 0.5827 |
| 17 | ETH | 2026-03-01 | -7.0 | 0.7445 | 1.0000 | 0.3613 |
| 18 | XLM | 2026-03-22 | 5.0 | 0.7440 | 0.8750 | 0.5476 |
| 19 | TAO | 2026-03-22 | -7.0 | 0.7424 | 0.8750 | 0.5434 |
| 20 | HBAR | 2026-04-12 | -7.0 | 0.7255 | 0.8750 | 0.5012 |
| 21 | HBAR | 2026-03-01 | -5.0 | 0.7221 | 0.8750 | 0.4928 |
| 22 | PEPE | 2026-03-01 | -5.0 | 0.7221 | 0.8750 | 0.4928 |
| 23 | FIL | 2026-03-01 | 0.0 | 0.7088 | 0.8750 | 0.4596 |
| 24 | XLM | 2026-04-12 | -10.5 | 0.6534 | 0.8750 | 0.3209 |

## Observed offset behavior

Offsets are not stable across all cycles.

Examples:

    BTC:    -7.0 -> +5.0 -> 0.0
    ETH:    -7.0 -> +5.0 -> 0.0
    TAO:    -7.0 -> -7.0 -> 0.0
    RENDER: -5.0 -> -7.0 -> 0.0
    FIL:     0.0 -> +3.0 -> +7.0
    HBAR:   -5.0 -> +3.0 -> -7.0
    XLM:    +3.0 -> +5.0 -> -10.5
    PEPE:   -5.0 -> +5.0 -> +7.0

Initial interpretation:

    Best offset appears cycle/regime-dependent.
    Do not assume a fixed per-asset phase lead/lag yet.

## Strongest alignments

Highest-scoring observations:

    BTC 2026-04-12     score 0.9097
    RENDER 2026-04-12  score 0.8716
    ETH 2026-03-22     score 0.8572
    PEPE 2026-03-22    score 0.8572
    BTC 2026-03-22     score 0.8555

These are candidates for manual chart review.

## Important limitation

V1 is a retrospective full-cycle matcher.

It uses completed cycle data to compare observed pivots against the template. Therefore, V1 is not a live predictor.

Future live/partial-cycle work should add:

    --as-of-ts
    partial marker scoring
    pending-marker status
    no future candle access beyond as_of_ts

## Next research questions

1. Does a high template_match_score correlate with forward return after the 0.618 or 0.786 marker?
2. Are strong scores more common during BTC B-wave / alt-rotation environments?
3. Are offsets clustered by asset class or sector?
4. Does volume confirmation improve precision?
5. Does relative strength versus BTC improve precision?
6. Does 4h matching improve timing quality compared to 1d?
7. Can the nested 10.5-day Breath Spiral Overlay explain intra-cycle spikes?

## Boundary

Allowed:

    research review
    historical waveform validation
    manual chart inspection
    future label generation

Out of scope:

    direct buy/sell logic
    execution targets
    decision_gate behavior
    execution_planner behavior
    executor behavior
