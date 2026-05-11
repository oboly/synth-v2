# Breath Curve Template Matcher v1 Smoke Findings

Status: research-only  
Scope: market-only / account-agnostic  
Writes: none  
Orders: none  

## Purpose

Record the first smoke-test results for the A+ 21-day Breathline Curve Template Matcher.

V1 only measures waveform alignment and pivot-match quality. It does not define downstream use.

## Test setup

Command shape:

    python -m src.research.breath_curve_template_matcher_v1 \
      --symbol SYMBOL \
      --venue bitvavo \
      --interval 1d \
      --anchor-date 2026-03-01 \
      --cycle-days 21 \
      --tolerance-hours 36 \
      --json

Offset grid:

    -10.5, -7, -5, -3, 0, +3, +5, +7, +10.5

## BTC offset inspection

Anchor:

    2026-03-01

Best BTC result:

    best_offset = -7.0
    best_score  = 0.7822
    shape_score = 1.0000
    timing_score = 0.4554

Offset table:

| Offset days | Score | Shape | Timing |
|---:|---:|---:|---:|
| -10.5 | 0.6903 | 1.0000 | 0.2257 |
| -7.0 | 0.7822 | 1.0000 | 0.4554 |
| -5.0 | 0.7221 | 0.8750 | 0.4928 |
| -3.0 | 0.6476 | 0.8750 | 0.3065 |
| 0.0 | 0.5958 | 0.7500 | 0.3644 |
| 3.0 | 0.6819 | 0.8750 | 0.3922 |
| 5.0 | 0.5957 | 0.6250 | 0.5518 |
| 7.0 | 0.5323 | 0.6250 | 0.3933 |
| 10.5 | 0.5381 | 0.6250 | 0.4078 |

## Basket smoke run

| Symbol | Best offset | Score | Shape | Timing |
|---|---:|---:|---:|---:|
| BTC | -7.0 | 0.7822 | 1.0000 | 0.4554 |
| ETH | -7.0 | 0.7445 | 1.0000 | 0.3613 |
| TAO | -7.0 | 0.7826 | 1.0000 | 0.4566 |
| RENDER | -5.0 | 0.7971 | 1.0000 | 0.4928 |
| FIL | 0.0 | 0.7088 | 0.8750 | 0.4596 |
| HBAR | -5.0 | 0.7221 | 0.8750 | 0.4928 |
| XLM | 3.0 | 0.7788 | 1.0000 | 0.4471 |
| PEPE | -5.0 | 0.7221 | 0.8750 | 0.4928 |

## Initial interpretation

The first smoke run confirms that the matcher is technically functional and that best phase offset is not uniform across assets.

Observed examples:

    BTC / ETH / TAO  -> -7.0 days
    RENDER / HBAR / PEPE -> -5.0 days
    FIL -> 0.0 days
    XLM -> +3.0 days

This supports the research idea that some assets may lead or lag the 21-day breathline template differently.

## Boundary

These findings are not trading signals.

Allowed use:

    research review
    waveform alignment measurement
    pivot-match quality comparison
    historical validation planning

Out of scope for V1:

    buy/sell decisions
    target execution
    selection_engine modifiers
    decision_gate rules
    execution_planner logic
