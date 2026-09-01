# Multi-Horizon Rotation C1 Final Holdout Evaluator v1

Issue: #593
Status: research-only, C1-only final-holdout evaluation contract

## Purpose

Evaluate the integrity-gated final-holdout artifact for the frozen selected
candidate only:

```text
C1 -> ADVANCE_TO_FINAL_HOLDOUT
```

The evaluator is separate from the discovery/validation runners. It does not
change their phase isolation or semantics.

## Input boundary

The sole evaluation input is a JSONL file named exactly:

```text
final_holdout_c1_rows_v1.jsonl
```

It is the output of the integrity-gated C1 final-holdout builder. The evaluator
does not read a split manifest, integrity artifact, database, network source, or
builder summary. Those are upstream construction gates, not evaluator inputs.

Each nonblank JSONL row is checked to have `candidate_id = C1` before any other
row field, including outcomes, is parsed. Any other value fails closed. Canonical
nondecreasing 15-minute `asof_ts` ordering, unique per-asof identity, finite-or-
null numeric fields, and all other frozen row parsing checks are enforced by the
shared streaming evaluator semantics.

## Metrics

The evaluator reuses the frozen sufficient-statistic and temporal semantics in:

- `multi_horizon_rotation_validation_v1`
- `multi_horizon_rotation_validation_streaming_v1`

It reports only C1:

- sample count, complete count, coverage and missingness;
- correlation against B0 and B1;
- raw forward IC at 15m, 1h, 4h, and 24h, each with paired sample count,
  Fisher-z 95% confidence interval, and approximate p-value;
- incremental partial correlation against B0 and B1 at every forward horizon,
  with the same uncertainty fields;
- persistence, sign flips, and chop reversions;
- lead/lag around B1 turns; and
- B0 pressure-state regime stability.

The frozen twelve-hypothesis Holm-Bonferroni family is retained for the four C1
forward-IC results (`holm_family_size=12`). No new selection threshold, percent
gate, recommendation, decision gate, or promotion result is introduced.

## Bounded memory

Rows are consumed one at a time. Retained state is limited to online pair/triple
statistics, per-market temporal state, fixed +/-16-sample lead/lag windows,
regime aggregates, and a single as-of cohort. No full JSONL rows or candidate
history are retained.

## Runner

```text
python -m src.research.run_multi_horizon_rotation_c1_final_holdout_evaluator_v1 \
  --input-jsonl <directory>/final_holdout_c1_rows_v1.jsonl \
  --output-json <directory>/final_holdout_c1_evaluation_v1.json
```

## Safety

```text
research_only=1
market_only=1
database_reads=0
database_writes=0
account_awareness=0
decision_gate=none
execution_planner=none
executor=none
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
