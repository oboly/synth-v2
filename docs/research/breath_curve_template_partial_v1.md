# Breath Curve Template Partial Matcher v1

Status: research-only  
Scope: market-only / account-agnostic  
DB writes: none  
Orders: none  

## Purpose

Run the 21-day Breath Curve Template Matcher with an `as_of_ts` cutoff.

This avoids future leakage by loading and scoring only candles available at or before the `as_of_ts`.

## Why this exists

The full-cycle matcher is retrospective. It can say whether a completed cycle matched the breathline template.

The partial matcher asks a harder question:

    Could the waveform already be recognized before the later 1.000 pulse?

Key checkpoints:

    0.618 second dip / higher-low
    0.786 ignition / pre-spike

## Inputs

- symbol
- anchor date
- as_of_ts
- cycle_days
- phase offset grid
- tolerance_hours
- min_due_markers

## Scoring

Only markers with expected timestamp at or before `as_of_ts` are due.

Future markers are not scored.

Partial score:

    partial_match_score =
        0.55 * partial_shape_score
      + 0.30 * partial_timing_score
      + 0.15 * marker_coverage_score

If fewer than `min_due_markers` are due, score is forced to zero.

## Marker statuses

    FUTURE
    DUE_MISSING
    OBSERVED_PARTIAL_WINDOW
    OBSERVED_CLOSED_WINDOW

## Boundary

V1 only measures partial waveform alignment and partial pivot-match quality.

It does not define downstream use.

Out of scope:

    buy/sell logic
    selection_engine modifiers
    decision_gate behavior
    execution_planner behavior
    executor behavior

## Usage

At approximately the 0.618 checkpoint:

    python -m src.research.run_breath_curve_template_partial_v1 \
      --symbol BTC \
      --venue bitvavo \
      --interval 1d \
      --anchor-date 2026-04-12 \
      --as-of-ts 2026-04-25 \
      --cycle-days 21 \
      --tolerance-hours 36

At approximately the 0.786 checkpoint:

    python -m src.research.run_breath_curve_template_partial_v1 \
      --symbol BTC \
      --venue bitvavo \
      --interval 1d \
      --anchor-date 2026-04-12 \
      --as-of-ts 2026-04-29 \
      --cycle-days 21 \
      --tolerance-hours 36

## Required ratio guard

For checkpoint tests, use `--required-ratio`.

This prevents a later phase offset from winning only because important markers are still in the future.

Examples:

    --required-ratio 0.618

means the 0.618 marker must be due and matched for the offset to score.

    --required-ratio 0.786

means the 0.786 marker must be due and matched for the offset to score.

Without this guard, an offset can look strong while only earlier markers are due. That is useful for broad partial matching, but not strict checkpoint validation.
