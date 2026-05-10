# Synth v2.7 Account Position Latest Report Status — 2026-05-10

Status: read-only report
Runtime impact: none
Decision impact: none
Execution impact: none
Broker impact: none
Live trading: not enabled

## Purpose

The latest account position report reads the newest `account_position_snapshot` batch for a trading account/source.

It provides portfolio visibility from local DB state only.

## Boundary

Allowed:

- read `account_position_snapshot`
- summarize quantities and mark values
- run hard safety checks

Forbidden:

- broker calls
- DB writes
- order placement
- order cancellation
- decision_gate override
- execution_planner override
- executor live activation
