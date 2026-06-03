# Multi-Account Wallet Refresh V1

## Purpose

`account_wallet_refresh_v1` reads per-account wallet state (balances + open
orders) from Bitvavo and writes it to the DB. It is a private read-only runner.

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
4. `trading_account` row exists for the profile (account_code = `bitvavo_<profile>_read`)

## Files

| File | Role |
|------|------|
| `src/account/run_account_wallet_refresh_v1.py` | Runner — private read + DB write |
| `src/account/account_snapshot_models_v1.py` | Shared dataclasses |

## Credentials

Credentials are never stored in the DB, the repo, or webroot.

Each profile has a credential file at:

```
${SYNTH_ACCOUNT_ENV_DIR:-~/.config/synth/accounts}/<profile>.env
```

Odroid examples still use:

```
/home/theone/.config/synth/accounts/<profile>.env
```

Required keys in the file:

```
BITVAVO_API_KEY=<key>
BITVAVO_API_SECRET=<secret>
```

Profile slug rules:
- must match `[a-z0-9][a-z0-9_-]{0,62}`
- no uppercase, no spaces, no path separators, no `..`

The `credential_ref` concept (future):
- DB may store only `credential_ref = "local_env:joost"` — a pointer
- Never store the key or secret value in DB or logs
- Secrets are never printed, never written to HTML/JSON output

## What it writes

### `trading_account_balance_snapshot`

One row per currency per snapshot timestamp. Existing table, FK → `trading_account`.

### `account_open_order_snapshot`

One row per order per snapshot timestamp. No side restriction (both BUY and SELL).

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
  --account-env-dir /home/theone/.config/synth/accounts \
  --venue bitvavo \
  --output summary
```

Write mode:

```bash
SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA \
python -m src.account.run_account_wallet_refresh_v1 \
  --account-profile hugo \
  --account-env-dir /home/theone/.config/synth/accounts \
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
```

Expected summary output:

```
runner=account_wallet_refresh_v1 version=0.1
profile=hugo account_code=bitvavo_hugo_read
trading_account_id=2 venue=bitvavo
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

Hugo's refresh uses `--account-profile hugo` → `account_code=bitvavo_hugo_read`
→ `trading_account_id=<hugo>`. All DB writes are scoped to that ID. Joost's
`account_asset`, balance snapshot, and order snapshot rows are never touched.

## Safety markers

```
broker_writes=0
order_submission=0
db_writes=balance_snapshot+order_snapshot+account_asset_discovery
executor=none
```
