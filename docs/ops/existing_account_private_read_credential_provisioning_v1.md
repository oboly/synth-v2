# Provision a READ_ONLY_PRIVATE credential for an existing account v1

Issue: #634

This operator path attaches a **new** `READ_ONLY_PRIVATE` credential to an
already-existing, already-enabled `trading_account_id` + `venue` pair. It
never creates or replaces a `trading_account` row, never touches
`app_profile_trading_account_link`, and never reads, updates, revokes, or
rotates an existing `TRADE_EXECUTION` row.

PR scope is intentionally limited to this provisioning seam, its CLI, tests,
and this operator document. It does not modify or remove research functionality.

Module: `src/account_provisioning/existing_account_private_read_credential_provisioning_v1.py`
CLI: `python -m src.account_provisioning.run_provision_existing_private_read_credential_v1`

## Why an ACTIVE TRADE_EXECUTION row with `allowed_private_read=1` does NOT satisfy READ_ONLY_PRIVATE

Every canonical `TRADE_EXECUTION` credential is provisioned with
`allowed_private_read=1` (see
`src/account_provisioning/trade_execution_provisioning_v1.py`) because order
placement requires the same private-read capability that private-read-only
tooling needs. That overlap in capability flags does **not** collapse the two
into one binding.

The canonical binding grain — enforced at the application layer here, in
`src/account_provisioning/credential_binding_contract_v1.py`, and at the
database layer by the `uq_tac_active_account_venue_scope_v1` unique index
(`db/migrations/20260721_account_credential_binding_contract_v1.sql`) — is:

```text
trading_account_id + venue + permission_scope -> exactly one ACTIVE row
```

`permission_scope` is part of the grain, not a label on top of it. A caller
that resolves credentials through `required_permission_scope=READ_ONLY_PRIVATE`
(for example `src/account/private_read_credential_resolver_v1.py`) only ever
matches a row whose `permission_scope='READ_ONLY_PRIVATE'`; an ACTIVE
`TRADE_EXECUTION` row for the same account/venue is invisible to that lookup
regardless of its `allowed_private_read` value. Read-only tooling that must
never be capable of order writes should bind to a `READ_ONLY_PRIVATE` row
specifically, so that its credential-scope invariant is enforced by schema,
not by caller discipline.

This module therefore provisions a distinct row: same account, same venue,
`permission_scope=READ_ONLY_PRIVATE`, `allowed_order_write=0`. It never reads,
compares against, or reuses the existing `TRADE_EXECUTION` row.

## Separate credential scope invariant

`trading_account_id=5` (`account_code=bitvavo_joost_live`, `venue=bitvavo`)
already carries an ACTIVE `TRADE_EXECUTION` credential. After this module
runs, the same account carries **two** independent ACTIVE credential rows:

```text
trading_account_credential (account=5, venue=bitvavo, permission_scope=TRADE_EXECUTION)  -- untouched
trading_account_credential (account=5, venue=bitvavo, permission_scope=READ_ONLY_PRIVATE) -- new
```

Both are permitted to coexist ACTIVE simultaneously because
`uq_tac_active_account_venue_scope_v1` is scoped by `permission_scope`, not
just `trading_account_id + venue`. Provisioning the `READ_ONLY_PRIVATE` row
never inserts, updates, revokes, or rotates the `TRADE_EXECUTION` row, and
this module contains no SQL statement that can reach it (its only queries are
scoped with `AND permission_scope = 'READ_ONLY_PRIVATE'`).

If an ACTIVE `READ_ONLY_PRIVATE` row already exists for the account/venue,
the module reports `STATUS=ALREADY_PROVISIONED` and performs no insert. It
never silently replaces, rotates, or revokes an existing `READ_ONLY_PRIVATE`
row; rotation is a separate, explicitly authorized operation.

## Safety contract

`--check`:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
db_mutation=0
```

`--apply`:

```text
broker_private_calls<=2
broker_writes=0
order_submission=0
live_orders=0
live_authority_grant=0
kill_switch_mutation=0
service_mutation=0
```

No API key, API secret, encrypted envelope, master key, or fingerprint is
ever printed or logged by either mode.

## Operator flow

### `--check` (default; metadata-only)

```bash
python -m src.account_provisioning.run_provision_existing_private_read_credential_v1 \
  --trading-account-id 5 \
  --venue bitvavo \
  --check
```

Reports account existence, `enabled`, `account_mode`, and whether an ACTIVE
`READ_ONLY_PRIVATE` credential already exists (`STATUS=ALREADY_PROVISIONED`)
or the account is eligible (`STATUS=READY`) or blocked
(`STATUS=BLOCKED`, `BLOCKER=<reason>`). Performs zero broker calls, zero
decryption, and zero writes. Omitting both `--check` and `--apply` is
equivalent to `--check`.

### `--apply` (explicit mutation)

```bash
python -m src.account_provisioning.run_provision_existing_private_read_credential_v1 \
  --trading-account-id 5 \
  --venue bitvavo \
  --apply
```

`--apply`:

1. Re-checks readiness (fails closed before prompting if the account is
   missing, disabled, venue-mismatched, or already provisioned).
2. Loads `SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY` — fails closed before any
   prompt if missing.
3. Prompts for the Bitvavo API key and API secret with hidden echo
   (`getpass`) only. Secrets are never accepted via `argv`.
4. Validates the plaintext credential with the canonical real validator
   (`src/account_provisioning/bitvavo_credential_validator_v1.py`), which
   itself requires `SYNTH_BROKER_PRIVATE_READ_PERMISSION` to be set (fails
   closed before any broker call otherwise) and calls only `get_balance()`
   then `get_open_orders()` — no order-write or withdrawal endpoint is
   reachable from this path.
5. Persists a new `ACTIVE` row **only** when validation reports
   `VALID_PRIVATE_READ`: `permission_scope=READ_ONLY_PRIVATE`,
   `allowed_private_read=1`, `allowed_order_write=0`,
   `allowed_withdrawal=0`, `validation_state=VALID_PRIVATE_READ`,
   `validated_ts_utc=<UTC now>`.

If validation is `INVALID` or `VALIDATION_UNAVAILABLE` (network/server
failure, missing gate), no row is ever inserted — there is no intermediate
`UNVALIDATED` row and therefore nothing to half-provision or roll back.

## Odroid production acceptance

Target: `trading_account_id=5`, `account_code=bitvavo_joost_live`,
`venue=bitvavo`.

Run `--check` first on the host holding the production master key
(`SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY` or the host-local key file) to confirm
`STATUS=READY`. Then run `--apply` interactively (hidden-echo prompts require
a TTY) to attach the new `READ_ONLY_PRIVATE` credential. This does not
create, enable, or touch any systemd timer, does not grant LIVE trading
authority, and performs no order mutation — it inserts exactly one
`trading_account_credential` row and nothing else.
