# Canonical `trading_account.account_mode` contract (Issue #551)

Status: implemented in the shared model and every canonical consumer listed
below. No production `trading_account` row has been changed by this change;
the data migration in
`docs/ops/trading_account_live_readonly_mode_migration_v1.md` is prepared
but explicitly **not applied**.

## Background

The SELL LIVE readiness audit (`docs/ops/sell_live_production_schema_migration_closure_v1.md`,
Issue #562) found that `trading_account_id` 2 and 3 (`bitvavo_synth_read`,
`bitvavo_joost_read`) are real Bitvavo accounts used only as read-only
wallet/position snapshot sources, both permanently provisioned with
`live_trading_enabled=0`. Prior to this change, `trading_account.account_mode`
supported only two values, `paper` and `live`, and every canonical consumer
required `account_mode == "live"` to imply `live_trading_enabled == True`.
Accounts 2/3 therefore had no value that could represent their real shape
("real broker data" + "never execution-eligible") without either falsely
claiming simulated data (`paper`) or falsely implying execution-eligibility
(`live`, the pre-existing and still-current classification, which is why
`sell_live_activation_controller_v1 --check` blocks `PRECHECK` with
`ACCOUNT_MODE_EVIDENCE_INCONSISTENT` for both).

This was a genuine schema/model gap, not a data-quality bug: `account_mode`
was conflating two independent facts (data realism vs. execution
eligibility) into one two-valued field.

## Canonical model

Single source of truth: `src/account/account_mode_contract_v1.py`.

| `account_mode` | Real broker? | `live_trading_enabled` | Execution-eligible? |
| --- | --- | --- | --- |
| `paper` | No (simulated) | `False` | Never |
| `live_readonly` | Yes | `False` | Never |
| `live` | Yes | `True` | Subject to decision_gate permission, credential scope, LIVE authority, and kill switch |

`live_readonly` accounts may use `READ_ONLY_PRIVATE` credential bindings
(`src/account_provisioning/credential_binding_contract_v1.py`) exactly like
`live` accounts do for read access; they may never be bound to a
`TRADE_EXECUTION` scope credential and can never resolve to an executor
`RUNTIME_MODE_LIVE` (or any other executor runtime mode).

`src.account.account_mode_contract_v1` exposes:

- `SUPPORTED_ACCOUNT_MODES`: the exact three-value set.
- `EXECUTION_ELIGIBLE_ACCOUNT_MODES`: `{"live"}` only.
- `is_account_mode_live_trading_enabled_consistent(account_mode, live_trading_enabled)`:
  the shared mechanical agreement check (`paper`/`live_readonly` require
  `False`, `live` requires `True`; any unsupported `account_mode` returns
  `False`, i.e. fails closed).
- `is_execution_eligible_account_mode(account_mode)`: `True` only for
  `live`.

No other module redefines this vocabulary or the agreement check; every
consumer below imports it.

## Two distinct fail-closed outcomes

These are deliberately different reason codes, because they mean different
things:

- **`ACCOUNT_MODE_EVIDENCE_INCONSISTENT`**: the `account_mode` /
  `live_trading_enabled` pairing itself is invalid (e.g. `account_mode="live"`
  with `live_trading_enabled=False` -- accounts 2/3's state before the data
  migration below is applied).
- **`ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE`**: the pairing is canonically
  consistent (`live_readonly` with `live_trading_enabled=False`), but the
  account_mode itself is permanently excluded from execution. This is the
  expected, correct outcome for a read-only snapshot account, not an error
  condition to fix.

## Canonical consumers updated

- `src/account/account_mode_contract_v1.py` (new, canonical, shared)
- `src/decision_gate/automatic_exit_gate_v1.py` -- `_evaluate_automatic_exit_candidate_permission_base_v1`
  rejects `live_readonly` with `REASON_ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE`
  before ever reaching the LIVE permission-evaluation branch.
- `src/decision_gate/automatic_buy_gate_v1.py` -- same shape;
  `live_readonly` is rejected before the free-quote-balance staleness check
  and LIVE permission-evaluation branch.
- `src/decision_gate/automatic_buy_account_allocation_evidence_contract_v1.py` --
  binds `account_mode` verbatim (unchanged responsibility) but now accepts
  all three canonical values instead of two.
- `src/entry_policy/automatic_buy_execution_handoff_application_v1.py` --
  `resolve_automatic_buy_executor_mode_v1` explicitly rejects
  `live_readonly` with `ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE` before any
  executor-mode lookup; `live_readonly` is also deliberately absent from
  `_ACCOUNT_MODE_TO_EXECUTOR_MODE`.
- `src/execution_planner/automatic_exit_execution_handoff_application_v1.py` --
  same shape for `resolve_automatic_exit_executor_mode_v1`.
- `src/ops/sell_live_activation_controller_v1.py` -- `_phase_precheck` uses
  the shared consistency check and blocks `live_readonly` with
  `ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE`, not a controller-local special
  case.

`account_provisioning_service_v1.py` is unchanged: it only ever provisions
new accounts as `paper` and never touches `live_readonly`/`live`.

## What this does not do

- No production `trading_account` row is changed by this repository change.
- No `live_trading_enabled`, credential, LIVE permission, or kill-switch
  mutation is part of this change.
- No new execution path or account is created.
- decision_gate is not bypassed anywhere: `live_readonly` fails closed
  through the exact same gate functions every other account_mode goes
  through, just earlier and with a more precise reason code.
