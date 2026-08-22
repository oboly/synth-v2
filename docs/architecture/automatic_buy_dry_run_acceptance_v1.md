# Automatic BUY DRY_RUN acceptance producer v1

Issue #471 adds the bounded acceptance producer that proves the canonical
automatic BUY path -- through the Issue #474 decision-gate-owned account
allocation evidence -- composes into a persisted DRY_RUN shared executor
handoff, with no live/broker/credential authority anywhere in the path.

## Why this exists

A previous #471 attempt (PR #473, reverted) accepted account-owned
decision-gate fields (`account_mode`, `account_enabled`,
`live_trading_enabled`, `automatic_buy_execution_enabled`, balances,
exposure) directly from operator-controlled JSON. `build_runtime_item_v1`
did not yet exist to re-bind those fields to a canonical source, so an
operator could describe a real LIVE account as PAPER and bypass the
`account_mode=live + live_trading_enabled=0` fail-closed guard. That is an
architecture violation of the `decision_gate` account-permission boundary
and was reverted rather than merged.

Issue #474 (`docs/architecture/automatic_buy_account_allocation_evidence_v1.md`)
closed that prerequisite: `automatic_buy_runtime_repository_v1.build_runtime_item_v1`
now unconditionally replaces every account-owned field on a runtime input --
regardless of what is persisted -- with a freshly-loaded, decision-gate-owned
`AutomaticBuyAccountAllocationEvidenceV1` snapshot before the candidate/gate/
planner path ever runs. This producer is the first caller that exercises that
guarantee end to end, including a real persisted executor handoff.

## Composition

```text
caller-controlled source/setup evidence (bounded JSON)
-> automatic_buy_source_runtime_input_writer_v1
   (immutable automatic_buy_runtime_input_v1 row; account-owned columns are
   safe fail-closed placeholders that are never read for any decision)
-> automatic_buy_runtime_repository_v1.build_runtime_item_v1
   (canonical #474 account allocation evidence, #279 strategy bucket
   history, #318 account protection, venue execution constraints)
-> automatic_buy_runtime_orchestrator_v1.evaluate_automatic_buy_runtime_item_v1
   (automatic_buy_candidate_v1 -> automatic_buy_gate_v1 ->
   automatic_buy_planner_v1 -> append-only automatic_buy_evaluation_audit_v1)
-> automatic_buy_execution_handoff_application_v1.submit_automatic_buy_plan_to_shared_handoff_v1
   -> shared #206 executor_execution_handoff, forced DRY_RUN
```

## Caller-controlled input contract

`AutomaticBuySourceRuntimeInputRequestV1` (in
`src/entry_policy/automatic_buy_source_runtime_input_writer_v1.py`) is the
entire caller-controlled surface. It carries only market/setup evidence and
the identity needed to locate canonical account evidence:

- `trading_account_id`, `venue`, `asset_id`, `market`, `strategy_bucket_id`
  -- identity only, selecting *which* account's canonical evidence to load;
  never that account's permission state;
- `strategy_id`, `strategy_version`, `setup_id`, `setup_ready`,
  `current_price`, `entry_zone_low/high`, `re_entry_zone_low/high`,
  `setup_evidence_id`, `setup_observed_ts_utc`, `evaluation_ts_utc`,
  `source_provenance`.

There is no field for `account_enabled`, `account_mode`,
`live_trading_enabled`, `automatic_buy_execution_enabled`, any balance,
exposure, bucket-amount, open-position, blocking-conflict, or protection
fact. The CLI JSON parser (`run_automatic_buy_dry_run_acceptance_v1.parse_source_request_from_json`)
additionally rejects any unknown/forbidden key before opening a DB
connection, so an operator payload that tries to smuggle one of those fields
fails immediately with `FORBIDDEN_OR_UNKNOWN_INPUT_FIELDS`.

The writer persists the account-owned columns as fixed, documented
fail-closed placeholders (disabled, PAPER, no execution permission, zero
balance, blocking conflict). `build_runtime_item_v1` overwrites every one of
them with canonical evidence before any candidate/gate/planner logic runs --
this producer's placeholders can never influence a permission outcome no
matter what value they hold.

## Idempotency

`automatic_buy_source_runtime_input_writer_v1` derives
`source_snapshot_key` as the SHA-256 of the exact caller-controlled fields.
The same logical source snapshot always reuses the same persisted row and
`automatic_buy_runtime_input_id`. A persisted row found under that key whose
stored evidence does not match the current request fails closed with
`AutomaticBuySourceRuntimeInputConflictError` rather than silently reusing
mismatched evidence.

Downstream, `automatic_buy_evaluation_audit_v1` is append-only and
idempotency-keyed exactly as the Phase 4/7B runtime already guarantees
(`docs/architecture/automatic_buy_runtime_v1.md`), and the shared executor
handoff is deduplicated by `(plan_source, plan_reference_id)`. A replay of
the identical request therefore produces the same
`runtime_input_id`/`source_snapshot_key`/`handoff_id`/`plan_reference_id`
with no duplicate rows or plan legs.

## DRY_RUN-only, no broker/credential/order authority

The CLI hardcodes `executor_mode=DRY_RUN`, `runtime_owner=gurkdb`,
`executor_identity=shared-executor-v1`. There is no flag to override any of
the three. `resolve_automatic_buy_executor_mode_v1`'s only permitted
override is `DRY_RUN`, so this holds regardless of whether the canonical
evidence resolves the account as PAPER or LIVE.
`ExecutionHandoffRepositoryV1.intake` never resolves executor credentials
for `DRY_RUN` (`executor_credential_binding_id` is always `NULL`), never
requires LIVE authority, and never calls a broker. The producer additionally
asserts this postcondition on the returned handoff before reporting success.

A LIVE account with `live_trading_enabled=false` still fails at
`automatic_buy_gate_v1` exactly as Issue #474/#399 already prove -- this
producer adds no LIVE-specific bypass, weakening, or special-casing of any
account.

Safety markers on every run:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_authority=0
credential_calls=0
```

## Usage

```bash
python -m src.entry_policy.run_automatic_buy_dry_run_acceptance_v1 --input-json path/to/evidence.json
```

The command prints `STARTED`/`FINISHED` markers, one structured JSON result
line (`runtime_input_id`, `source_snapshot_key`, `candidate_state`,
`gate_state`, `gate_reason`, `planner_state`, `planner_reason`,
`handoff_id`, `plan_reference_id`, `plan_content_hash`, `executor_mode`,
`runtime_owner`, `executor_identity`, `safety_markers`), and exits non-zero
only on an invalid-input or repository/contract error -- a determinate
`REJECTED`/`DENIED` outcome for an ineligible candidate/account is a
successful run, not a failure.
