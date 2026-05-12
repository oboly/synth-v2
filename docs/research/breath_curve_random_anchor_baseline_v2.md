# Breath Curve Random-Anchor Baseline v2

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
DB writes: none  

## Purpose

Test whether Breath Curve research-policy outcomes outperform same-symbol random anchors.

This report answers:

    Does 0.618 + offset_match beat same-symbol random anchors?

## Method

The runner samples random anchors per symbol from the same tested date window as the existing Breath Curve partial-to-full research lane.

For each random anchor, it recomputes:

- partial checkpoint recognition
- full-cycle template match
- selected partial offset
- offset-match status against best full offset
- return to 1.000 marker
- return to 1.272 marker
- synthetic research-policy return

The random baseline is recomputed from candles and matcher logic. It is not derived from already-selected policy rows.

## Comparisons

The report compares:

- real 0.618 all vs random 0.618 all
- real 0.618 offset_match vs random 0.618 offset_match
- real 0.786 all vs random 0.786 all
- real 0.786 offset_match vs random 0.786 offset_match

## Metrics

For each bucket:

- total random candidates
- eligible count
- selection rate
- average policy return
- median policy return
- positive rate
- best/worst return
- same-window hold-to-1.000
- same-window hold-to-1.272
- real policy minus random
- policy minus hold baselines
- per-symbol buckets

## Leakage controls

Random anchors are:

- same-symbol only
- sampled within the same tested date window
- excluded if too close to known real anchors, default +/- 3 days
- required to have sufficient candle coverage before partial checkpoint and through full-cycle target window

Non-selected random anchors remain in the denominator for selection-rate calculation.

## Default runner

    python -m src.research.run_breath_curve_random_anchor_baseline_v2 \
      --start-date 2026-03-01 \
      --end-date 2026-04-12 \
      --samples-per-symbol 100 \
      --seed 260512 \
      --output table

## Output

Generated CSV outputs are written under:

    data/research/breath_curve_random_anchor_baseline_v2/

These outputs are research artifacts and should remain ignored unless explicitly promoted.

## Boundary

This is not a strategy.

Forbidden downstream use:

- selection_engine modifier
- decision_gate rule
- execution_planner instruction
- executor/order logic
- live or paper execution trigger
- broker API call
- broker write

Correct path:

    random-anchor baseline -> validation report -> regime tests -> optional later market-only feature proposal
