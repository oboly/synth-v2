# Breath Curve Research Policy Report v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Orders: none  
DB writes: none  

## Purpose

Read and summarize DB-backed Breath Curve research-policy backtest runs.

## Report sections

    policy runs
    orphan run check
    latest checkpoint comparison
    latest by-symbol summary

## Runner

    python -m src.research.run_breath_curve_research_policy_report_v1 --limit 20

## Boundary

This report is read-only.

It does not:

    call broker APIs
    submit orders
    write to DB
    create decision_gate rules
    create execution_planner logic
    touch executor logic
