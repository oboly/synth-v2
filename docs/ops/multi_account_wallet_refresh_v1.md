# Multi-Account Wallet Refresh V1

## Purpose

`account_wallet_refresh_v1` is the canonical `ACCOUNT_STATE_SNAPSHOT_REFRESH`
producer on **Odroid**. It reads per-account wallet state (balances + open
orders) from Bitvavo, derives the matching persisted position snapshot, and
writes one aligned account-state evidence bundle to the DB. It is a private
read-only runner.

It does not:

- submit orders
- cancel orders
- write to any broker/exchange
- change `decision_gate`
- change `execution_planner`
- change `executor`

## Truth model

DB is source of truth.
`/var/www/html/synth/accounts/<profile>/` is render output only.
No account state is stored in web folders.
Credentials live outside the repo and outside webroot.

## Dependencies

1. Migration `20260603_multi_account_asset_foundation_v1.sql` — creates `venue_market` and `account_asset`
2. Migration `20260603_account_open_order_snapshot_v1.sql` — creates `account_open_order_snapshot`
3. Bitvavo market sync run at least once (`--write-db`) so `venue_market` rows exist for account asset discovery
4. `trading_account` row exists for the account being refreshed

## Files

| File | Role |
|------|------|
| `src/account/run_account_wallet_refresh_v1.py` | Runner — private read + DB write |
| `src/account/account_snapshot_models_v1.py` | Shared dataclasses |

## Credentials

Canonical contract: `docs/architecture/account_credential_binding_contract_v1.md`.

Contract requirement: account selection does not imply credential selection.
Wallet refresh must resolve the exact linked `trading_account_id`, then resolve
exactly one active credential profile by:

```text
trading_account_id + venue + READ_ONLY_PRIVATE
```

Canonical production credential source:

```text
db_encrypted
```

Legacy profile environment credentials may be represented only as:

```text
legacy_profile_env_deprecated
```

That state is explicit migration-only. It must never be a default, implicit
fallback, or repository-global `.env` fallback.

Current implementation state for PR A:

- the schema and pure binding contract are defined
- runtime wallet-refresh callers are not yet migrated to permission-scope
  credential resolution
- legacy repository-global environment credential fallback still exists in
  legacy runtime paths
- PR B must enforce scoped runtime resolution and remove that legacy fallback

Profile slug rules:
- must match `[a-z0-9][a-z0-9_-]{0,62}`
- no uppercase, no spaces, no path separators, no `..`

Canonical relationship model:

```text
app user/profile
→ explicit account access
→ trading_account
→ venue

trading_account
→ max one active READ_ONLY_PRIVATE credential per venue
→ max one active TRADE_EXECUTION credential per venue
```

Notes:

- a dashboard/app profile is not itself a trading account
- a credential is not itself a trading account
- public market-data surfaces use no account credential
- private account refresh uses the trading account's active READ credential
- executor-only write actions would use the trading account's active WRITE credential
- dashboard/reporting code reads DB snapshots only

Contract requirement: private clients must use an explicit resolved credential
profile. Repository-global `.env` credentials are not a valid multi-account
binding. PR B must wire wallet-refresh runtime callers to enforce this boundary.

## What it writes

### `trading_account_balance_snapshot`

One row per currency per snapshot timestamp. Existing table, FK → `trading_account`.

### `account_open_order_snapshot`

One row per order per snapshot timestamp. No side restriction (both BUY and SELL).

### Aligned account-state evidence

Migration `20260815_account_state_snapshot_alignment_v1.sql` adds the
append-only `account_state_snapshot_run_v1` header. A `COMPLETE` run is emitted
only in the wallet producer's single DB transaction after all of these exact
same-refresh components have persisted successfully:

- balance rows (`trading_account_balance_snapshot`),
- derived position rows (`account_position_snapshot`), and
- a `COMPLETE` `account_open_order_snapshot_run_v1` header whose count equals
  the normalized/persisted open-order result.

The header retains component source names, common snapshot timestamp, counts,
and the exact open-order run ID. It is therefore authoritative even when an
account has no positive positions or zero open orders. Any private-read,
position derivation, persistence, or count failure rolls back the transaction
and creates no `COMPLETE` account-state run. The legacy standalone position
writer may still support diagnostics, but it never creates this aligned header
and is not authoritative input for a later automatic-exit runtime.

Position identity remains the immutable persisted row identity
`account_position_snapshot:<account_position_snapshot_id>`; it is not a random
per-refresh value.

### `account_asset`

One row per (trading_account, venue_market). Created on discovery:

| Field | Default |
|-------|---------|
| `is_visible` | true |
| `is_candidate_enabled` | true |
| `is_order_proposal_enabled` | false |
| `is_hidden` | false |
| `source` | WALLET_DISCOVERY or OPEN_ORDER_DISCOVERY |

Source precedence on conflict: `MANUAL_ADD` is never overwritten by discovery.

## Usage

Dry-run:

```bash
SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA \
python -m src.account.run_account_wallet_refresh_v1 \
  --account-profile joost \
  --credential-source db \
  --venue bitvavo \
  --output summary
```

Write mode:

```bash
SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA \
python -m src.account.run_account_wallet_refresh_v1 \
  --account-profile hugo \
  --credential-source db \
  --venue bitvavo \
  --write-db \
  --output summary
```

## Migration apply

Do not require `mariadb synth` local socket access on a dev laptop.
Use the same repo-connected `get_connection()` pattern as the market sync doc,
swapping the SQL path as needed:

```text
db/migrations/20260603_multi_account_asset_foundation_v1.sql
db/migrations/20260603_account_open_order_snapshot_v1.sql
db/migrations/20260721_account_credential_binding_contract_v1.sql
```

Expected summary output example:

```
runner=account_wallet_refresh_v1 version=0.2
profile=joost account_code=bitvavo_joost_read
trading_account_id=2 venue=bitvavo
credential_source=db
[INFO] private read-only; no broker writes; no order submission
snapshot_ts_utc=2026-06-03 14:00:00
balance_count=8
order_count=5
account_asset_inserted=2
account_asset_existing=6
balance_snapshot_writes=8
order_snapshot_writes=5
broker_writes=0
order_submission=0
executor=none
```

## Account isolation

Refresh writes are always scoped to exactly one `trading_account_id`. One account's
`account_asset`, balance snapshot, and order snapshot rows must never touch another
account's rows.

The aligned header is additionally scoped by `trading_account_id + venue +
source_name + snapshot_ts_utc`. Retry of the same persisted evidence reuses the
same header; a different account or venue creates independent evidence.

## Safety markers

```
broker_writes=0
order_submission=0
db_writes=balance_snapshot+order_snapshot+account_asset_discovery
executor=none
```
