# Decision Gate Audit Writer v1

`decision_gate_audit_writer_v1` is the append-only writer for `decision_gate_audit_log`.

It records account-scoped decision gate outcomes for audit and later downstream references. It does not grant permission, does not create execution plans, does not call the executor, and does not submit orders.

## Boundary

This writer is account-aware logging only.

It does not:

- change `selection_engine` behavior
- change decision permission rules
- call `execution_planner`
- call `executor`
- call broker/private APIs
- perform broker writes
- submit, cancel, or place orders
- enable `LIVE` or `LIVE_ARMED`

Safety markers are fixed for this writer:

```text
broker_private_calls=0
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
execution_planner=none
executor=none
```

## Scope Requirements

Every inserted audit row must include account scope:

- `trading_account_id` required
- `user_id` nullable for now
- `strategy_profile_id` nullable for now
- `strategy_candidate_id` nullable where relevant
- `venue`
- `asset_id`
- `interval_code`
- `asof_ts_utc`
- `created_ts_utc`

`symbol` is display-only and nullable. Account identity must never be inferred from `asset_id`, `symbol`, `venue`, or interval.

This writer does not alter market-only tables and does not add `user_id` to market-only tables.

## Execution Mode

The contract supports explicit execution modes:

- `PAPER`
- `LIVE_DRY_RUN`
- `LIVE_ARMED`
- `LIVE`

Writer v1 only inserts `PAPER` and `LIVE_DRY_RUN` rows. `LIVE_ARMED` and `LIVE` are rejected by the writer in this task so no live runtime can be implied.

## Append-Only Semantics

`src/decision_gate/audit_writer_v1.py` performs only:

```sql
INSERT INTO decision_gate_audit_log ...
```

It does not update or delete audit rows. Corrections should be represented by later append-only rows with clear reason codes and upstream references.

## Smoke Runner

Dry-run smoke:

```bash
python -m src.decision_gate.run_decision_gate_audit_writer_smoke_v1 \
  --execution-mode PAPER \
  --output table
```

Write smoke:

```bash
python -m src.decision_gate.run_decision_gate_audit_writer_smoke_v1 \
  --execution-mode PAPER \
  --write-db \
  --output table
```

The write smoke uses `upstream_ref_type=SMOKE_TEST` by default. It prints row counts before and after the insert so the expected delta is visible. The default smoke row uses synthetic display values and does not imply any trading permission.

## Later Planner Reference

When runtime ownership is finalized, `execution_planner` can reference the decision gate audit row through:

- `upstream_ref_type = DECISION_GATE_AUDIT_LOG`
- `upstream_ref_id = <decision_gate_audit_log_id>`

That reference should mean "the planner used this account-scoped decision result as input." It must not mean the planner can skip permission checks, infer account scope, or submit orders.

## Reason And Safety Payloads

`reason_codes_json` should include machine-readable decision reasons, for example:

```json
{
  "reason_codes": ["DUPLICATE_ACTIVE_PLAN"],
  "permission_granted": false
}
```

`safety_markers_json` should include the fixed no-broker/no-executor markers. Future live dry-run or preflight flows may add more markers, but broker writes and order submission must remain `0` until a separate live activation task hard-gates them.
