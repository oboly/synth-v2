# Exact-account private-read account-state refresh (Issues #614, #631, #636)

Status: repository code only. No production timer or LIVE authorization is
created by this change. `broker_private_calls<=2` per run, `broker_writes=0`,
`order_submission=0`, `live_orders=0`, `live_authority_grant=0`,
`kill_switch_mutation=0`, `service_mutation=0`.

## Files

```text
src/account/run_exact_account_state_refresh_v1.py
src/account/private_read_capability_compatible_resolver_v1.py
src/account/exact_account_state_persistence_v1.py
src/account/private_read_credential_resolver_v1.py
```

The original strict `READ_ONLY_PRIVATE` resolver remains unchanged. Issue #631
adds a separate opt-in resolver for bounded private-read consumers. Issue #636
adds a separate exact-account persistence seam so an explicitly selected LIVE
account can persist evidence without weakening the legacy read-only position
writer guard.

## Why this is a separate seam

`run_account_wallet_refresh_v1.py` remains the profile-primary dashboard
refresh path and refuses LIVE-capable accounts. The exact-account runner is
instead invoked with an explicit `trading_account_id` + `venue` and never
uses an app-profile fallback.

Production account 5 has one canonical validated credential with:

```text
permission_scope=TRADE_EXECUTION
allowed_private_read=1
allowed_order_write=1
allowed_withdrawal=0
validation_state=VALID_TRADE_EXECUTION
```

The canonical credential contract already requires private-read capability for
a `TRADE_EXECUTION` credential. Creating a duplicate Bitvavo credential solely
for balances/open-orders would add unnecessary secret lifecycle complexity.
Issue #631 therefore permits this exact-account private-read runner to opt into
capability-compatible resolution without changing the generic credential
binding contract or the strict `READ_ONLY_PRIVATE` resolver.

## Credential contract

The compatible resolver accepts exactly one eligible credential for the same
exact account + venue:

1. validated `READ_ONLY_PRIVATE`, or
2. validated `TRADE_EXECUTION` with its canonical required capabilities.

For either path the credential must be `ACTIVE`, `db_encrypted`, have
`allowed_private_read=1`, `allowed_withdrawal=0`, a non-null validation
timestamp, and pass envelope/account/venue/key-version/fingerprint checks.
`TRADE_EXECUTION` additionally remains subject to its canonical
`VALID_TRADE_EXECUTION` and `allowed_order_write=1` requirements.

If both scopes yield an eligible credential, resolution fails closed with
`AMBIGUOUS_PRIVATE_READ_CAPABLE_CREDENTIALS`. No implicit permission broadening
is added to `validate_credential_binding()`.

## Broker boundary

The compatible resolver always constructs the broker client through:

```text
BitvavoClient.for_private_read(...)
```

The exact-account runner calls only:

```text
client.get_balance()
client.get_open_orders()
```

It imports or calls no broker-write/order/withdrawal operation. A source
credential having execution capability does not make that capability reachable
from this consumer.

## Account isolation

Identity and credential resolution are independently bound to the exact
`trading_account_id` + `venue`. Encrypted-envelope account/venue mismatches fail
closed. Evidence from another account is never projected onto the requested
account.

The #636 persistence seam independently reloads the exact account by
`trading_account_id + venue`, verifies `account_code`, requires `enabled=1`, and
fails closed on any identity mismatch. It intentionally does not reject
`live_trading_enabled=1`, because LIVE eligibility has already been explicitly
selected by this exact-account operator seam.

## Persistence contract (#636)

The legacy position snapshot writer still contains and enforces:

```text
live_trading_enabled == 0
```

for its own profile/read-only runtime. That guard is not removed or weakened.

`src/account/exact_account_state_persistence_v1.py` instead reuses only local DB
snapshot primitives. It performs no broker call and has no broker client,
order-submit, decision-gate, execution-planner or executor path.

For `--write-db` the caller transaction performs:

1. exact account reload and identity verification
2. balance snapshot writes
3. local position derivation from that exact balance snapshot
4. open-order snapshot writes
5. persisted component-count verification
6. COMPLETE open-order header
7. COMPLETE account-state bundle header
8. commit only after all prior steps succeed

Any exception is handled by the exact refresh runner with `conn.rollback()`.
Therefore a failed component must not leave a partial COMPLETE bundle.

Position `raw_json` produced by the exact seam records the actual
`account_mode` and `live_trading_enabled` state while retaining
`broker_submission=false` and `position_mutation=false`.

## CLI

Dry-run first:

```bash
SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA \
python -m src.account.run_exact_account_state_refresh_v1 \
  --trading-account-id 5 \
  --venue bitvavo \
  --output summary
```

Without `--write-db`, no DB write occurs.

Only after the dry-run is accepted, write one canonical COMPLETE bundle:

```bash
SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA \
python -m src.account.run_exact_account_state_refresh_v1 \
  --trading-account-id 5 \
  --venue bitvavo \
  --write-db \
  --output summary
```

Expected credential lines for production account 5:

```text
runner=exact_account_state_refresh_v1 version=0.3
trading_account_id=5 account_code=bitvavo_joost_live
venue=bitvavo account_mode=live
credential_source=db_encrypted
permission_scope=TRADE_EXECUTION
validation_state=VALID_TRADE_EXECUTION
[INFO] private read-only; no broker writes; no order submission
```

The summary must still end with:

```text
broker_private_calls=2
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

No API key, API secret, encrypted envelope, master key, or fingerprint is
printed.

## Explicitly out of scope

- no credential mutation, rotation, re-encryption or permission change
- no extra Bitvavo credential provisioning
- no systemd timer or scheduled job
- no LIVE authority grant
- no kill-switch mutation
- no decision-gate, execution-planner or executor change

## Safety

```text
broker_private_calls<=2 per bounded run
broker_writes=0
order_submission=0
live_orders=0
credential_mutation=0
credential_rotation=0
live_authority_grant=0
kill_switch_mutation=0
service_mutation=0
decision_gate=none
execution_planner=none
executor=none
```
