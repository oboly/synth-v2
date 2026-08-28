# Automatic BUY account-allocation evidence v1 (Issue #474)

## Problem

PR #473 attempted to add a DRY_RUN acceptance producer for the automatic BUY
runtime (Issue #456 Stage B / #399). Manual review reverted it because it let
operator JSON supply account-owned decision-gate evidence directly:
`account_mode`, `live_trading_enabled`, `automatic_buy_execution_enabled`,
balances, conflicts, bucket amount, open positions, and asset exposure. That
made the acceptance harness an unauthorized account-permission/allocation
authority -- a `selection_engine -> account state` / `external note -> buy
logic` style architecture violation.

The underlying gap: `decision_gate` already owned some of this evidence
(`trading_account` identity/mode/LIVE flag; COMPLETE account-state snapshots;
`strategy_bucket_account_config_v1`; account protection), but no single
canonical, decision-gate-owned projection existed for:

- `automatic_buy_execution_enabled`
- `proposed_position_amount_eur`
- `current_bucket_amount_eur`
- `current_open_positions`
- `current_asset_exposure_pct`

bound to one `trading_account_id` + `venue`/`asset_id`/`market` + one
observed/effective evaluation timestamp. This is what #474 adds.

## The projection

`src/decision_gate/automatic_buy_account_allocation_evidence_contract_v1.py`
defines `AutomaticBuyAccountAllocationEvidenceV1` (pure dataclass + fail-closed
validator, no DB import).
`src/decision_gate/automatic_buy_account_allocation_evidence_repository_v1.py`
assembles it from canonical sources only
(`load_automatic_buy_account_allocation_evidence_v1`, DB reads, no broker,
executor, or order import). The loader's signature has no parameter for any
of the five fields above, or for `account_enabled`/`account_mode`/
`live_trading_enabled` -- there is structurally no way for a caller to
override decision-gate-owned evidence (see
`tests/test_automatic_buy_account_allocation_evidence_repository_v1.py::test_no_caller_override_parameters_exist`).

## Field ownership

| Field | Owner | How |
| --- | --- | --- |
| `account_enabled` / `account_mode` / `live_trading_enabled` | `trading_account` | bound verbatim by `trading_account_id` |
| `automatic_buy_execution_enabled` | new `automatic_buy_account_permission_v1` (decision_gate) | resolved via `automatic_buy_account_permission_contract_v1`; absence of a row means denied, same convention as `automatic_exit_account_permission_v1` |
| `free_quote_balance_eur` | COMPLETE account-state bundle's `trading_account_balance_snapshot` (EUR row) | same COMPLETE-bundle pattern as `automatic_exit_runtime_repository_v1` |
| `blocking_conflict` | COMPLETE bundle's `account_open_order_snapshot` for the candidate's market | same pattern as the exit side |
| `current_open_positions` | COMPLETE bundle's `account_position_snapshot` (positive rows) | count, account-wide |
| `current_bucket_amount_eur` | same position rows, valued in EUR at the latest fresh `market_price_snapshot` per held asset | sum, account-wide |
| `current_asset_exposure_pct` | candidate asset's own position value ÷ account NAV (positions + free quote balance) × 100 | derived, clamped to `[0, 100]` |
| `proposed_position_amount_eur` | the account's own already-resolved `strategy_bucket_account_config_v1.max_position_amount_eur` | bound verbatim; unresolved config or an unset ceiling yields `Decimal("0")`, which the existing gate/candidate-amount checks already reject the same way they reject any other non-positive proposed amount |

### Automatic-BUY execution permission (new)

`automatic_buy_execution_enabled` previously had no persisted owner at all.
`automatic_buy_account_permission_v1` (migration
`db/migrations/20260822_automatic_buy_account_permission_v1.sql`) is a new,
append-only, decision-gate-owned table mirroring
`automatic_buy_live_decision_gate_permission_v1`'s exact shape (immutable
rows, revocation-only supersession, effective-window resolution, ambiguous
overlap fails closed). It grants no executor authority, credential, broker
permission, kill-switch state, or order authority, and it is wholly separate
from the LIVE-only decision-gate permission
(`automatic_buy_live_decision_gate_permission_v1`): this is the general
opt-in that applies to both PAPER and LIVE account modes.

### Bucket-amount / open-positions scope: a documented approximation

The schema does not tag a held position with the strategy bucket that opened
it -- there is no `strategy_bucket_id` column on `account_position_snapshot`
or `account_asset`. `current_bucket_amount_eur` and `current_open_positions`
are therefore computed **account-wide**, not bucket-scoped. This is
deliberately conservative: when an account runs more than one concurrently
enabled bucket, this over-counts exposure against each bucket's own ceiling
rather than under-counting it, so it can only make the gate *more*
restrictive, never less. A true per-bucket position ledger would require new
storage (tagging a position with the bucket that opened it) and is out of
scope for #474; this limitation is deliberate, not an oversight.

## Composition: where this replaces caller trust

`src/entry_policy/automatic_buy_runtime_repository_v1.py`'s
`build_runtime_item_v1` is the sole production caller. Before Issue #474, it
built `AutomaticBuyGateContextV1` directly from the persisted
`automatic_buy_runtime_input_v1` row's own account-owned columns -- exactly
the trust that a writer of that table (the future #471 producer) must never
be allowed to abuse. It now:

1. Resolves the account's effective `strategy_bucket_account_config_v1` row
   itself (the same pure resolver the gate uses) to obtain
   `max_position_amount_eur`. An unresolved/ambiguous config, or one with no
   configured `max_position_amount_eur`, fails the whole item closed
   (`STRATEGY_BUCKET_CONFIGURATION_UNRESOLVED` /
   `PROPOSED_POSITION_AMOUNT_POLICY_UNRESOLVED`) rather than letting the gate
   see a fabricated amount.
2. Loads `AutomaticBuyAccountAllocationEvidenceV1` for the exact
   `(trading_account_id, venue, asset_id, market)` identity on the runtime
   input.
3. Replaces the in-memory `runtime_input`'s account-owned fields with the
   evidence's values via `dataclasses.replace` (the persisted DB row itself
   is untouched; the table stays append-only). The gate only ever sees the
   freshly-derived canonical values, never the row's own columns.

The `automatic_buy_runtime_input_v1` schema and its `input_contract_version`
V1/V2 idempotency identity (`automatic_buy_idempotency_key_v1`/`_v2`) are
unchanged: none of the five fields, `account_enabled`, `account_mode`, or
`automatic_buy_execution_enabled` were ever part of the hashed idempotency
evidence, so replay identity is unaffected by this change.

One consequence worth noting explicitly: if a V1-contract row's underlying
`trading_account` has since become `account_mode="live"`, the freshly-bound
evidence will trip `validate_runtime_input_v1`'s existing
`LIVE_RUNTIME_INPUT_REQUIRES_CONTRACT_V2` check and the item fails closed.
This is intentional -- a stale PAPER-contract snapshot must not silently keep
evaluating under PAPER semantics after the account itself has moved to LIVE.

## What this does not change

- `account_mode="live"` with `live_trading_enabled=False` (production
  accounts 2/3's actual shape at the time this doc was written) is bound
  faithfully by the evidence projection and rejected by the gate's own
  `REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT` exactly as before -- see
  `tests/test_automatic_buy_runtime_repository_v1.py::test_build_runtime_item_v1_live_account_flag_false_still_rejected_by_gate_end_to_end`.
  Issue #551 later introduced a canonical third `account_mode` value,
  `live_readonly` (see `docs/architecture/account_mode_contract_v1.md`), for
  exactly this real-broker/read-only shape; once accounts 2/3 are migrated
  to `live_readonly` (data migration prepared, not yet applied -- see that
  doc), they bind as canonically consistent evidence and are instead
  rejected by `REASON_ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE`, not
  `REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT`. `automatic_buy_gate_v1`'s
  evidence-binding contract itself is otherwise unchanged by #551.
- No executor, broker, or order import exists anywhere in the new modules.
- No production DB mutation, credential provisioning, `live_trading_enabled`
  mutation, kill-switch change, or LIVE authority grant is part of this
  change; the new migration is an artifact only, matching this repository's
  existing automatic-BUY migration convention.
