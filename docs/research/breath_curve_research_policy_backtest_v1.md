# Breath Curve Research Policy Backtest v1

Status: research-only  
Layer: market-only / account-agnostic  
Orders: none  
Broker calls: none  
DB writes: none  

## Purpose

This script evaluates hypothetical entry/exit research policies using the existing partial-to-full breath curve backtest output.

It does not define live strategy behavior.

## Input

The script consumes CSV output from:

    src/research/backtest_breath_curve_partial_to_full_v1.py

Required columns include:

    symbol
    anchor_date
    checkpoint_ratio
    selected_partial_score
    selected_partial_offset_days
    return_to_1000_pct
    return_to_1272_pct
    offset_matches_best_full

## V1 policy concept

The V1 research policy asks:

    If a partial checkpoint looked strong enough,
    what would the labelled return have been toward 1.000 and/or 1.272?

Default policy:

    checkpoint = 0.618
    min_partial_score = 0.70
    TP1 = 1.000 marker
    TP2 = 1.272 marker
    TP1 weight = 50%
    TP2 weight = 50%
    cost_bps = 20

This is a label-based research simulation, not a path-aware execution backtest.

## Example

    python -m src.research.backtest_breath_curve_research_policy_v1 \
      --input-csv data/research/breath_curve_partial_to_full_v1/example.csv \
      --checkpoints 0.618 \
      --min-partial-score 0.70 \
      --tp1-weight 0.50 \
      --tp2-weight 0.50 \
      --cost-bps 20 \
      --output table

## Boundary

Allowed:

    research review
    policy hypothesis testing
    comparison of checkpoint usefulness
    comparison by symbol / offset match / checkpoint

Not allowed:

    live trading
    order submission
    decision_gate rules
    execution_planner logic
    executor logic
    selection_engine modifier without later validation

## Output naming

Output files include:

    policy_name
    UTC timestamp with microseconds

This prevents two policy runs in the same second from overwriting each other.
