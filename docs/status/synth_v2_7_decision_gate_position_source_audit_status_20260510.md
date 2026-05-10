# Synth v2.7 Decision Gate Position Source Audit Status — 2026-05-10

Status: read-only audit
Runtime impact: none
Decision impact: none
Execution impact: none
Broker impact: none
Live trading: not enabled

## Purpose

The decision gate position source audit verifies whether a local `account_position_snapshot` source is safe and complete enough for future decision_gate reads.

This does not connect decision_gate to the source yet.

## Checks

The audit verifies:

- trading account exists
- trading account is enabled
- live trading is disabled
- latest position snapshot exists
- no duplicate symbols in the latest batch
- no negative quantities
- no missing mark prices
- hard execution safety checks are zero
- broker write permission is not granted

## Boundary

Allowed:

- read local DB state
- report readiness

Forbidden:

- broker calls
- DB writes
- order placement
- order cancellation
- decision_gate code changes
- execution_planner code changes
- executor live activation
