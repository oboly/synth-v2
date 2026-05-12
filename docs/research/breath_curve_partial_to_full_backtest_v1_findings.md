# Breath Curve Partial-to-Full Backtest v1 Findings

Status: research-only  
Scope: market-only / account-agnostic  
Downstream use: undefined until historical validation  

## Purpose

Record the first partial-to-full backtest for the A+ 21-day Breathline Curve Template Matcher.

This test asks:

    Could the second half of the breathline have been anticipated from the 0.618 or 0.786 checkpoint?

## Setup

Symbols:

    BTC, ETH, TAO, RENDER, FIL, HBAR, XLM, PEPE

Anchors:

    2026-03-01
    2026-03-22
    2026-04-12

Checkpoints:

    0.618
    0.786

Cycle:

    21 days

Offset grid:

    -10.5, -7, -5, -3, 0, +3, +5, +7, +10.5

Tolerance:

    36 hours

Future target guard:

    1.000 marker must still be in the future for selected offset.

## Summary

| Checkpoint | OK samples | Eligible future | Partial score >= 0.70 | Avg return to 1.000 | Positive return rate | Offset match rate |
|---:|---:|---:|---:|---:|---:|---:|
| 0.618 | 24 | 24 | 24 | +7.1762% | 95.83% | 41.67% |
| 0.786 | 24 | 24 | 24 | +0.9411% | 62.50% | 20.83% |

## Initial interpretation

The 0.618 checkpoint was materially stronger than the 0.786 checkpoint in this small sample.

Working interpretation:

    0.618 = primary early recognition checkpoint
    0.786 = later confirmation / momentum checkpoint
    1.000 = outcome / pulse target

This supports the idea that the useful edge may occur near the second dip / higher-low rather than near the visible pre-spike.

## Strong examples

Examples with positive return to the 1.000 marker:

| Symbol | Anchor | Checkpoint | Offset | Partial score | Return to 1.000 | Offset matched full? |
|---|---|---:|---:|---:|---:|---|
| TAO | 2026-03-01 | 0.618 | -7.0 | 0.8402 | +26.6212% | yes |
| ETH | 2026-03-22 | 0.618 | 0.0 | 0.8272 | +14.1624% | no |
| ETH | 2026-03-01 | 0.618 | -7.0 | 0.8002 | +13.1889% | yes |
| PEPE | 2026-03-01 | 0.618 | -3.0 | 0.8228 | +11.4882% | no |
| FIL | 2026-03-01 | 0.618 | 0.0 | 0.7794 | +10.7413% | yes |
| RENDER | 2026-03-01 | 0.618 | -5.0 | 0.8785 | +10.0822% | yes |
| BTC | 2026-03-22 | 0.618 | 0.0 | 0.8272 | +9.5546% | no |
| PEPE | 2026-03-22 | 0.618 | -3.0 | 0.8706 | +9.2507% | no |
| FIL | 2026-03-22 | 0.618 | -3.0 | 0.8728 | +8.9612% | no |

## RENDER observation

RENDER remains one of the cleanest alt candidates in the first research batch.

Observed examples:

    RENDER 2026-03-01 checkpoint 0.618 -> +10.0822%, offset matched full
    RENDER 2026-03-22 checkpoint 0.618 -> +3.3403%, offset matched full
    RENDER 2026-04-12 checkpoint 0.618 -> +5.8993%, offset matched full
    RENDER 2026-04-12 checkpoint 0.786 -> +8.6305%, offset matched full

Initial interpretation:

    RENDER showed repeatable partial-to-full structure in this small sample.

## Important caveats

This is a very small sample:

    8 assets
    3 anchors
    2 checkpoints
    48 tests total

The threshold `partial_score >= 0.70` was not selective in this run because all OK samples exceeded it.

Future versions should test:

    higher thresholds
    baseline comparison
    randomized anchors
    more historical anchors
    4h candles
    volume confirmation
    relative strength versus BTC
    return distribution versus naive buy-and-hold over the same window

## Boundary

These findings are not trading signals.

Allowed:

    research review
    validation planning
    partial-cycle predictive-quality testing

Out of scope:

    direct buy/sell logic
    execution targets
    decision_gate behavior
    execution_planner behavior
    executor behavior
