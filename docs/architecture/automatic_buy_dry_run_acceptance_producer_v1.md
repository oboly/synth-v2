# Automatic BUY DRY_RUN acceptance producer v1 (Issue #471)

## Problem

Issue #399 built an audit-only automatic BUY runtime
(`automatic_buy_runtime_orchestrator_v1`) and, separately, the typed
seam that forwards an already-staged plan to the shared #206 executor
handoff (`automatic_buy_live_handoff_composition_v1`). Nothing owned the
first step: immutable, controlled creation of an
`automatic_buy_runtime_input_v1` row for a deliberate acceptance run.

A prior attempt (PR #473) added that missing writer, but let its caller-JSON
input carry every account-owned decision-gate field directly --
`account_mode`, `live_trading_enabled`, `automatic_buy_execution_enabled`,
free quote balance, proposed position amount, current bucket
amount/open-positions/exposure. That made the acceptance harness an
unauthorized account-permission/allocation authority, and the PR was
reverted. Issue #474 then added the canonical, decision-gate-owned
`AutomaticBuyAccountAllocationEvidenceV1` projection so this rebuild has a
lawful source for exactly those fields. This document describes that
rebuild.

## Components

`src/entry_policy/automatic_buy_runtime_input_writer_v1.py`

- `AutomaticBuySourceEvidenceV1`: the only caller-controlled input shape.
  Every field is market/setup evidence or bare locating identity
  (`trading_account_id`, `venue`, `asset_id`, `market`,
  `strategy_bucket_id`, `source_snapshot_key`). There is structurally no
  field for any account-owned value -- adding one would reintroduce the
  exact defect PR #473 was reverted for.
- `write_automatic_buy_runtime_input_v1`: persists exactly one immutable
  row via `INSERT ... ON source_snapshot_key UNIQUE`, always binds
  `input_contract_version=2` (LIVE-capable), and fills every account-owned
  column with a neutral placeholder (`account_mode="paper"`,
  `automatic_buy_execution_enabled=True`, `live_trading_enabled=False`,
  balances/exposure at zero, `proposed_position_amount_eur=1`). These
  placeholders carry no evidentiary meaning: `build_runtime_item_v1`
  (Issue #474) unconditionally overwrites all twelve of them with a
  freshly-loaded, decision-gate-owned evidence snapshot before
  `automatic_buy_gate_v1` ever sees the row. A replay with byte-identical
  caller-controlled evidence reuses the existing row
  (`idempotent_existing`); a replay reusing the same
  `source_snapshot_key` with different caller-controlled evidence fails
  closed with `AUTOMATIC_BUY_RUNTIME_INPUT_IDENTITY_CONFLICT`.

`src/entry_policy/run_automatic_buy_dry_run_acceptance_producer_v1.py`

- The one bounded CLI/composition root for controlled acceptance. It reads
  a JSON file restricted to exactly the `AutomaticBuySourceEvidenceV1`
  fields; presence of any account-owned key (`account_mode`,
  `live_trading_enabled`, `account_enabled`,
  `automatic_buy_execution_enabled`, balances, exposure, bucket amount,
  open positions, `max_automatic_buy_notional_eur`, or the internal
  `automatic_buy_runtime_input_id`/`input_contract_version` columns) is a
  fail-closed `FORBIDDEN_ACCOUNT_OWNED_SOURCE_FIELDS` error before any DB
  call, not a silently-ignored key.
- `executor_mode`, `runtime_owner`, and `executor_identity` are fixed
  module constants (`DRY_RUN`, `gurkdb`, `shared-executor-v1`
  respectively) -- there is no CLI flag or caller input that can change
  them.
- Composes exactly:
  `write_automatic_buy_runtime_input_v1`
  `-> build_runtime_item_v1` (binds canonical #474 account evidence,
  strategy bucket, account protection, venue constraints)
  `-> evaluate_and_handoff_automatic_buy_runtime_item_v1` (unchanged
  `automatic_buy_gate_v1` / `automatic_buy_planner_v1` / #206 shared
  handoff `intake`, `executor_mode_override="DRY_RUN"`).
- A LIVE account whose canonical evidence shows `live_trading_enabled =
  False` is rejected by `automatic_buy_gate_v1`
  (`ACCOUNT_MODE_LIVE_FLAG_EVIDENCE_INCONSISTENT`) before the planner or
  handoff are ever reached -- this producer adds no bypass and no special
  case; every LIVE-mode row goes through the identical gate logic every
  other caller of this runtime uses.
- DRY_RUN intake never resolves a credential binding
  (`executor_credential_binding_id` is always `NULL`) and never touches
  LIVE authority or the kill switch, because `ExecutionHandoffRepositoryV1
  .intake()` only exercises those paths for non-DRY_RUN modes.

## Idempotency / replay

Identity is deterministic end to end because every layer keys off content
derived from the same caller-controlled source evidence:

1. `automatic_buy_runtime_input_v1.source_snapshot_key` (writer, this
   Issue).
2. `automatic_buy_evaluation_audit_v1.idempotency_key`
   (`automatic_buy_idempotency_key_v2`, unchanged #399/#474 contract).
3. `executor_execution_handoff.(plan_source, plan_reference_id)`
   (`derive_automatic_buy_plan_reference_id_v1`, unchanged #399 Phase 6
   contract).

Replaying the same source evidence reuses all three rows; a conflicting
replay (same identity key, different evidence) fails closed at whichever
layer detects it first, and never produces a duplicate plan leg.

## Safety

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_authority=0
decision_gate=automatic_buy_gate_v1 (called, not bypassed)
execution_planner=automatic_buy_planner_v1 (called, not bypassed)
executor=execution_handoff_v1 (intake DRY_RUN only; no submission)
```

## Usage

Input JSON must contain exactly the `AutomaticBuySourceEvidenceV1` fields
(see `_ALLOWED_SOURCE_KEYS` in the runner module):

```bash
python -m src.entry_policy.run_automatic_buy_dry_run_acceptance_producer_v1 \
    --input-json /path/to/source_evidence.json
```

The runner prints one `STARTED`/safety-markers line, one JSON result line
(`runtime_input_id`, `source_snapshot_key`, `candidate_state`,
`gate_state`, `gate_reason`, `planner_state`, `planner_reason`,
`handoff_id`, `plan_reference_id`, `plan_content_hash`, `executor_mode`,
`runtime_owner`, `executor_identity`, `executor_credential_binding_id`,
`safety_markers`), and one `FINISHED`/`FAILED` summary line.
