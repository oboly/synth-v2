# CQ v1 model preregistration gate v1

Issue: #568
Phase: 2D0
Status: research-only, market-only, read-only

## Purpose

Phase 2B froze eligible canonical feature families. Phase 2C implemented replay-safe point-in-time extraction and a coverage report, but the repository does not yet contain a completed measured `coverage_summary.json` artifact.

Therefore this slice deliberately does **not** choose CQ v1 transforms, weights, or a formula. It freezes the gate that must be satisfied before those modeling choices may be committed.

This preserves the required order:

```text
feature eligibility freeze
-> PIT extraction
-> measured coverage artifact
-> model transformation/weight freeze
-> final holdout comparison
```

## Required coverage artifact

The gate accepts only a completed `cq_v1_pit_extractor_v1` summary with:

```text
terminal_state = FINISHED
sample_count > 0
last_shadow_id present
0 <= family/joint counts <= sample_count
joint count <= each family count
reported coverage == recomputed count / sample_count at 6 decimals
weights_assigned = 0
cq_v1_scores_emitted = 0
```

A valid artifact is canonicalized as sorted compact JSON and assigned a SHA-256 digest. The subsequent model-freeze slice must pin that exact digest so the coverage evidence cannot drift after model choices are made.

## Gate states

```text
BLOCKED_COVERAGE_ARTIFACT_REQUIRED
BLOCKED_INVALID_COVERAGE_ARTIFACT
READY_FOR_MODEL_FREEZE
```

## Explicitly forbidden here

```text
feature transforms
feature weights
CQ v1 formula
forward-outcome reads
holdout inspection
new feature-family discovery
production ranking changes
```

The gate is not an evaluator and has no access to future outcomes.

## Next slice

Once a completed Phase 2C coverage artifact passes this gate, Phase 2D1 may freeze a small deterministic transform/weight family against the pinned coverage artifact digest. Final outcome comparison remains a later slice.

## Safety

```text
research_only=1
market_only=1
account_awareness=0
db_writes=0
production_ranking_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
runtime_activation=0
```
