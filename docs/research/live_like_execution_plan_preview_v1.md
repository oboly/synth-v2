## Live-Like Execution Plan Preview V1

`run_live_like_execution_plan_preview_v1.py` is the next shadow-safe layer in the live-like vertical slice:

`DecisionPreview -> ExecutionPlanPreview`

This runner is file-input and file-output only.

## Purpose

This adapter reads a file-based `DecisionPreview` artifact and emits a file-based `ExecutionPlanPreview` artifact.

It is not the real `execution_planner`.

- no DB writes
- no broker private calls
- no broker writes
- no order submission
- no executor calls
- executor always disabled

It exists to make the vertical slice contract concrete in shadow mode before any real execution-planner path is introduced.

## Boundary

This runner is:

- research-only
- shadow-only
- preview-only

This runner is not:

- the real `execution_planner`
- a broker adapter
- an executor path
- an order path

It creates no executable intent. Executor remains disabled.

## Inputs

Required:

- `--decision-run-dir`

This points to a run directory such as:

```text
data/research/live_like_decision_preview_v1/run_<UTC_RUN_ID>/
```

Read files:

- `decision_preview_v1.json`
- `manifest_v1.json`

Optional:

- `--candidate-run-dir`
- `--mode` default `shadow`
- `--write-files` / `--no-write-files`
- `--output-root` default `data/research/live_like_execution_plan_preview_v1`

If `--candidate-run-dir` is omitted, the runner resolves `source_candidate_run_dir` from the decision manifest when available.

## Execution Plan Logic V1

### Shadow review

If:

- `decision_state == SHADOW_REVIEW`
- `permission_state == PREVIEW_ONLY_NOT_PERMISSION`

Then:

- `execution_plan_state=PREVIEW_ONLY_BLOCKED`
- `side=BUY` if `candidate.direction_pressure > 0`
- `side=SELL` if `candidate.direction_pressure < 0`
- `side=NONE` otherwise
- `max_notional_preview=null`
- `limit_price_preview=null` unless candidate context includes an observed price
- `ladder_steps_preview=()`
- `timeout_seconds=0`
- `cancel_conditions` includes `SHADOW_MODE_NO_PERMISSION`
- `executor_enabled=false`

### Watch candidate

If `decision_state == WATCH_CANDIDATE`:

- `execution_plan_state=WAIT_FOR_ENTRY_CONFIRMATION`
- `side=NONE`
- `cancel_conditions` includes `NOT_ENTRY_CANDIDATE_YET`

### Wait

If `decision_state == WAIT`:

- `execution_plan_state=WAIT`
- `side=NONE`
- `cancel_conditions` includes `WAIT_RETEST`

### Blocked

If `decision_state == BLOCKED`:

- `execution_plan_state=BLOCKED`
- `side=NONE`
- `cancel_conditions` includes the decision block reasons

## Always-On Safety

Always:

- `executor_enabled=false`
- `mode=shadow`
- `no_order_submission=true`

## Outputs

Default output root:

```text
data/research/live_like_execution_plan_preview_v1/
```

Per run:

```text
data/research/live_like_execution_plan_preview_v1/run_<UTC_RUN_ID>/
```

Files:

- `execution_plan_preview_v1.json`
- `execution_plan_preview_v1.jsonl`
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
- `account_tables_used=false`
- `mode=shadow`
- `source_decision_run_dir=<input>`
- `source_candidate_run_dir=<resolved or null>`

## Vertical Slice Path

This runner advances only one step in the path:

- `StrategyCandidate`
- `DecisionPreview`
- `ExecutionPlanPreview`
- `ShadowEvent`

It stops at `ExecutionPlanPreview`.

No real execution intent or executor permission is created here.
