## Live-Like Shadow Event V1

`run_live_like_shadow_event_v1.py` completes the shadow-safe vertical slice:

`StrategyCandidate -> DecisionPreview -> ExecutionPlanPreview -> ShadowEvent`

This runner is file-input and file-output only.

## Purpose

This adapter reads file-based candidate, decision-preview, and execution-plan-preview artifacts and emits a file-based `ShadowEvent` artifact.

It is not execution.

- no DB writes
- no broker private calls
- no broker writes
- no order submission
- no executor calls
- no live permission

`no_order_submitted` must always remain `true`.

## Boundary

This runner is:

- research-only
- shadow-only
- lifecycle logging only

This runner is not:

- execution
- paper trading
- live trading
- a broker adapter
- an executor path

## Inputs

Required:

- `--candidate-run-dir`
- `--decision-run-dir`
- `--execution-plan-run-dir`

These point to run directories such as:

```text
data/research/intraday_retest_reclaim_candidate_v1/run_<UTC_RUN_ID>/
data/research/live_like_decision_preview_v1/run_<UTC_RUN_ID>/
data/research/live_like_execution_plan_preview_v1/run_<UTC_RUN_ID>/
```

Read files:

- `strategy_candidate_v1.json`
- `decision_preview_v1.json`
- `execution_plan_preview_v1.json`

Optional:

- `--mode` default `shadow`
- `--write-files` / `--no-write-files`
- `--output-root` default `data/research/live_like_shadow_event_v1`

## Shadow Event Fields

The runner builds:

- `strategy_instance_id` from candidate
- `candidate_state` from candidate
- `decision_state` from decision preview
- `execution_plan_state` from execution plan preview
- `observed_price`
  - prefer candidate `current_price`, `ticker_price`, `observed_price`, or `price_at_emit`
  - otherwise `null`
- `event_ts_utc` from current UTC timestamp
- `no_order_submitted=true`

## Outputs

Default output root:

```text
data/research/live_like_shadow_event_v1/
```

Per run:

```text
data/research/live_like_shadow_event_v1/run_<UTC_RUN_ID>/
```

Files:

- `shadow_event_v1.json`
- `shadow_event_v1.jsonl`
- `manifest_v1.json`

## Manifest Safety

- `db_writes=0`
- `broker_private_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `decision_gate_changes=0`
- `execution_planner_changes=0`
- `executor=none`
- `executor_enabled=false`
- `no_order_submitted=true`
- `account_tables_used=false`
- `mode=shadow`
- `source_candidate_run_dir=<input>`
- `source_decision_run_dir=<input>`
- `source_execution_plan_run_dir=<input>`

## Vertical Slice Complete

This runner completes the shadow-only path:

- `StrategyCandidate`
- `DecisionPreview`
- `ExecutionPlanPreview`
- `ShadowEvent`

The next possible step is a chain runner or dashboard that reads these artifacts together.

The next step is not executor enablement.
