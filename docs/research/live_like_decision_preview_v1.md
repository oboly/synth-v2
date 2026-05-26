## Live-Like Decision Preview V1

`run_live_like_decision_preview_v1.py` is the next shadow-safe layer in the live-like vertical slice:

`StrategyCandidate -> DecisionPreview`

This runner is file-input and file-output only.

## Purpose

This adapter reads a file-based `StrategyCandidate` artifact and emits a file-based `DecisionPreview` artifact.

It is not the real `decision_gate`.

- no DB writes
- no broker private calls
- no broker writes
- no order submission
- no account-table reads
- no execution intent

It exists to make the vertical slice contract concrete in shadow mode before any real account-aware permission path is introduced.

## Boundary

This runner is:

- research-only
- shadow-only
- preview-only

This runner is not:

- the real `decision_gate`
- a broker/account adapter
- an execution planner
- an order path

Real account-aware permissions remain later.

## Inputs

Required:

- `--candidate-run-dir`

This points to a run directory such as:

```text
data/research/intraday_retest_reclaim_candidate_v1/run_<UTC_RUN_ID>/
```

Read file:

- `strategy_candidate_v1.json`

Optional:

- `--trading-account-id`
- `--mode` default `shadow`
- `--write-files` / `--no-write-files`
- `--output-root` default `data/research/live_like_decision_preview_v1`

## Decision Logic V1

### Entry candidate

If `candidate_state == ENTRY_CANDIDATE`:

- `decision_state=SHADOW_REVIEW`
- `permission_state=PREVIEW_ONLY_NOT_PERMISSION`
- `block_reasons` includes `SHADOW_MODE_NO_PERMISSION`

### Retest-active but not entry-ready

If `candidate_state` is one of:

- `SHALLOW_RETEST_ACTIVE`
- `NORMAL_RETEST_ACTIVE`
- `DEEP_RETEST_ACTIVE`

Then:

- `decision_state=WATCH_CANDIDATE`
- `permission_state=WAIT_FOR_ENTRY_CONFIRMATION`
- `block_reasons` includes `NOT_ENTRY_CANDIDATE_YET`

### Wait states

If `candidate_state` is one of:

- `IMPULSE_ACTIVE`
- `WAIT_RETEST`

Then:

- `decision_state=WAIT`
- `permission_state=NO_PERMISSION`
- `block_reasons` includes `WAIT_RETEST`

### Blocked states

If `candidate_state` is one of:

- `NO_CANDIDATE`
- `INVALIDATED`
- `STALE`

Then:

- `decision_state=BLOCKED`
- `permission_state=NO_PERMISSION`
- `block_reasons` includes the candidate state

## Always-On Safety

Always:

- `live_trading_enabled=false`
- `broker_write_permission=false`
- `account_awareness="none"` if no `trading_account_id`
- `account_awareness="configured_id_only"` if a `trading_account_id` is supplied

Notes must explain that this is preview-only and does not grant order permission.

## Outputs

Default output root:

```text
data/research/live_like_decision_preview_v1/
```

Per run:

```text
data/research/live_like_decision_preview_v1/run_<UTC_RUN_ID>/
```

Files:

- `decision_preview_v1.json`
- `decision_preview_v1.jsonl`
- `manifest_v1.json`

## Manifest Safety

- `db_writes=0`
- `broker_private_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `decision_gate_changes=0`
- `execution_planner_changes=0`
- `executor=none`
- `account_tables_used=false`
- `mode=shadow`
- `source_candidate_run_dir=<input>`

## Vertical Slice Path

This runner advances only one step in the path:

- `StrategyCandidate`
- `DecisionPreview`
- `ExecutionPlanPreview`
- `ShadowEvent`

It stops at `DecisionPreview`.

No real permission or order intent is created here.
