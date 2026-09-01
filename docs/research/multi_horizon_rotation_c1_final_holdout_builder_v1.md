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

Only after successful verification may holdout rows be built. On `--resume`, this
recompute-and-verify step runs again, before any further row is replayed.

## Canonical one-time holdout opening

There is no `--output-dir` argument. The runner takes `--split-manifest` and
`--source-integrity`, both of which must be named exactly `split_manifest_v1.json`
and `source_integrity_v1.json` and must live in the same directory. That directory
is the single canonical run directory, and every holdout artifact for this run
(`final_holdout_c1_rows_v1.jsonl`, `final_holdout_c1_summary_v1.json`, the
`.final_holdout_c1_rows_v1.jsonl.partial` streaming file, and the
`.final_holdout_c1_checkpoint_v1.json` checkpoint) is written there. There is
no way to reopen the holdout in a second location for the same frozen manifest.

Immediately after integrity verification succeeds and immediately before the
first holdout replay, the runner freezes a `RUNNING` checkpoint in that
directory. Its checkpoint schema binds:

```text
runner, runner_version, venue, candidate_id, manifest_sha256,
source_integrity_composite_sha256, phase, phase_start, phase_end,
last_completed_asof, asofs_completed, row_count, partial_bytes,
source_query_count, source_rows_read, terminal_state, updated_ts_utc
```

Once that checkpoint exists, a fresh (non-`--resume`) invocation always fails
closed: `RUNNING` or `INTERRUPTED` state can only be continued with
`--resume`, and `FINISHED` state can never be reopened.

## Interruption and resume

`SIGINT` and `SIGTERM` are handled explicitly: the runner flushes and fsyncs
the last fully committed as-of, marks the checkpoint `INTERRUPTED`, prints
exactly one `INTERRUPTED` line with no traceback, restores the previous signal
handlers, and exits `130` (SIGINT) or `143` (SIGTERM). No partially processed
as-of is ever committed.

`--resume` requires the canonical checkpoint and partial artifact to exist with
`terminal_state` `RUNNING` or `INTERRUPTED`. It re-verifies source integrity,
validates every checkpoint identity field, truncates the partial artifact back
to the checkpoint's committed byte offset, reconciles the row count, confirms
`last_completed_asof` belongs to the frozen holdout grid, and then continues
strictly after that as-of.

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

The runner is one-shot and refuses to overwrite an existing final-holdout artifact, summary, checkpoint, or partial artifact unless `--resume` is given for a `RUNNING`/`INTERRUPTED` checkpoint. See "Canonical one-time holdout opening" and "Interruption and resume" above.

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
