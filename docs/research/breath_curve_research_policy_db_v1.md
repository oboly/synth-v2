# Breath Curve Research Policy DB v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Orders: none  

## Purpose

Store breath curve research-policy backtest runs and rows in DB tables so they can be compared, queried, and later used by research dashboards.

This replaces ad-hoc CSV-only comparison for canonical results.

## Tables

    research_breath_curve_policy_run
    research_breath_curve_policy_result

## Source

The DB runner consumes output from:

    src/research/backtest_breath_curve_partial_to_full_v1.py

## Runner

    python -m src.research.backtest_breath_curve_research_policy_db_v1 \
      --input-csv data/research/breath_curve_template_matcher_v1/breath_curve_partial_to_full_v1_YYYY.csv \
      --policy-name breath_curve_research_policy_0618_v1 \
      --checkpoints 0.618 \
      --min-partial-score 0.70 \
      --tp1-weight 0.50 \
      --tp2-weight 0.50 \
      --cost-bps 20 \
      --write-db \
      --output table

## Boundary

Allowed:

    research storage
    policy comparison
    dashboard queries
    baseline comparison
    regime joins later

Not allowed:

    live order decisions
    broker submission
    decision_gate bypass
    execution_planner logic
    executor logic
    selection_engine modifier without later validation

## Source column aliases

The DB runner accepts these anchor date source columns:

    anchor_date
    anchor
    anchor_ts
    anchor_ts_utc
    anchor_datetime
    cycle_anchor
    cycle_anchor_date

Datetime values are normalized to:

    YYYY-MM-DD
