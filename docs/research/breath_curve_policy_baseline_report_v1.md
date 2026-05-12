# Breath Curve Policy Baseline Report v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
DB writes: none  

## Purpose

Read existing DB-backed Breath Curve research-policy rows and compare policy returns against simple same-window baselines.

This report is a measurement layer only.

## Baselines

This version compares:

- policy return
- same-window hold-to-1.000 return
- same-window hold-to-1.272 return
- checkpoint buckets
- offset-match buckets
- symbol buckets
- policy-name buckets

## Not included in v1

Random-anchor baseline is intentionally not implemented here.

Reason:

Random-anchor baseline requires sampling anchors from the candle universe and recomputing partial/full outcomes. It cannot be honestly derived from already-selected policy rows without selection bias.

## Runner

    python -m src.research.run_breath_curve_policy_baseline_report_v1 --limit-runs 20

## Boundary

Allowed:

- DB reads from research_breath_curve_policy_run
- DB reads from research_breath_curve_policy_result
- research comparison
- dashboard/report input

Forbidden:

- DB writes
- broker calls
- order generation
- selection_engine modifier
- decision_gate rule
- execution_planner logic
- executor logic
