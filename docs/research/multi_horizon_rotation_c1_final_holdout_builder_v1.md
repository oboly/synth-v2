# Multi-Horizon Rotation C1 Final Holdout Builder v1

Issue: #593
Status: research-only final-holdout dataset builder

## Purpose

Open the frozen final holdout exactly once for preregistered candidate `C1` after the canonical source-content integrity gate has been frozen and re-verified.

The pre-holdout selection is fixed:

```text
C1 -> ADVANCE_TO_FINAL_HOLDOUT
C2 -> REJECT_BEFORE_FINAL_HOLDOUT
C3 -> INSUFFICIENT_DATA
```

This runner does not reopen C2 or C3.

## Hard integrity gate

Before any final-holdout candidate replay or forward-label construction, the runner:

1. loads the frozen split manifest and requires `final_holdout_inspected=false`;
2. recomputes `multi_horizon_rotation_source_integrity_v1` against the canonical DB sources;
3. verifies equality with the frozen write-once `source_integrity_v1.json`;
4. fails closed on any drift.

Only after successful verification may holdout rows be built.

## Candidate scope

Exactly one frozen spec is allowed:

```text
candidate_id = C1
effective_horizon = VERY_SHORT
target operator timescale ~= 15m
```

No sign flip, recalibration, threshold change, candidate substitution, or formula change is permitted after discovery/validation inspection.

## Data and labels

The builder reuses the canonical #593 replay and row-building owners from the discovery/validation implementation:

- point-in-time observed asset universe;
- C1 replay implementation;
- B0 Rotation Pressure V1 PIT lookup;
- B1 comparable 15m return;
- B2 unavailable status;
- exact-boundary forward responses at 15m, 1h, 4h, 24h;
- phase-end purge so no outcome endpoint at/after the frozen source end is used.

Output:

```text
final_holdout_c1_rows_v1.jsonl
final_holdout_c1_summary_v1.json
```

The runner is one-shot and refuses to overwrite an existing final-holdout artifact, summary, or partial artifact.

## Isolation

The existing discovery/validation builder remains unchanged and continues to deny final-holdout access.

This separate runner exists specifically so holdout access cannot be obtained by adding a third phase to the ordinary builder CLI.

C2/C3 are never evaluated by this runner.

## Safety

```text
research_only=1
market_only=1
database_reads=1
database_writes=0
account_awareness=0
decision_gate=none
execution_planner=none
executor=none
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```

## Next step

The resulting `final_holdout_c1_rows_v1.jsonl` must be evaluated by a separate C1-only holdout evaluator that reuses the frozen validation metric semantics. No model change is allowed between dataset creation and evaluation.
