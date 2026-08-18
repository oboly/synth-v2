# Account Asset Management V1

## Purpose

`account_asset_management_v1` adds account-scoped asset management controls without requiring the account to buy the coin first.

The layer supports:

- wallet discovery after a Bitvavo buy
- manual add of synced Bitvavo EUR markets for one account only
- hide / disable / pause / re-enable per account only

## Dependency Status

Required dependencies:

1. Multi-account asset foundation committed
2. Account wallet dashboard committed and pushed with output path:
   - `/var/www/html/synth/accounts/<profile>/wallet.html`
   - `/var/www/html/synth/accounts/<profile>/wallet.json`

This backend assumes those dependencies are already satisfied.

## Truth model

- `asset` = global symbol identity
- `venue_market` = global Bitvavo market metadata
- `account_asset` = per-account settings and discovery
- balance / open-order snapshots = per `trading_account_id`
- DB = source of truth
- `/var/www/html/synth/accounts/<profile>/` = render output only
- credentials remain outside repo and outside webroot

## Hard boundaries

- account asset settings are account-scoped only
- no mutation of global `asset` flags for account preference changes
- no mutation of global `venue_market` flags for account preference changes
- Hugo changes must not affect Joost
- Joost changes must not affect Hugo
- add / hide / disable / pause / re-enable do not create orders
- add / hide / disable / pause / re-enable do not call broker
- add / hide / disable / pause / re-enable do not read private broker state
- hide / disable do not cancel open orders
- hide / disable do not alter historical wallet or order snapshots
- no `decision_gate` changes
- no `execution_planner` changes
- no executor changes

Required safety markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
executor=none
```

## Files

| File | Role |
|------|------|
| `src/account/account_asset_settings_v1.py` | Account-scoped backend mutations + DB repo |
| `src/account/run_account_asset_settings_v1.py` | Local-only CLI runner |
| `src/reporting/account_asset_management_v1.py` | Read-only UI-prep datasets and disabled action metadata |
| `db/migrations/20260603_account_asset_settings_v1.sql` | Adds missing account-asset settings fields |

## Schema handling

Existing `account_asset` foundation already provides:

- `trading_account_id`
- `venue_market_id`
- `is_visible`
- `is_candidate_enabled`
- `is_order_proposal_enabled`
- `is_hidden`
- `disabled_until_utc`
- `source`
- `created_ts`
- `updated_ts`

This batch adds only the missing settings-support fields:

- `disabled_reason`
- `first_seen_at_utc`
- `last_seen_at_utc`

It reuses existing `created_ts` / `updated_ts` instead of adding duplicate timestamp columns.

### Production schema reconciliation

Issue #333 tracks production drift where the three settings-support fields above are absent from the live `account_asset` table even though the repository runtime already reads and writes them.

`db/migrations/20260603_account_asset_settings_v1.sql` is additive and idempotent for the three columns. Existing rows are backfilled as follows:

- `first_seen_at_utc` from the row's existing `created_ts`;
- `last_seen_at_utc` from the row's existing `updated_ts`;
- `updated_ts` must remain byte-for-byte unchanged by the backfill.

The final invariant matters because the foundation column is defined with `ON UPDATE CURRENT_TIMESTAMP`. The migration therefore explicitly self-assigns `updated_ts = updated_ts` during the provenance backfill so the schema repair does not rewrite historical update evidence merely because new columns were populated.

Production application remains a separately authorized ops action. Repository merge or Issue #333 work alone does not authorize a production `ALTER TABLE` or data backfill.

## Supported actions

Local-only runner actions:

- `add_asset`
- `hide_asset`
- `disable_candidate`
- `pause_candidate_24h`
- `reenable_asset`

Runner example:

```bash
python -m src.account.run_account_asset_settings_v1 \
  add_asset \
  --account-profile hugo \
  --venue bitvavo \
  --market FET-EUR \
  --output summary
```

## Manual add behavior

Manual add uses synced `venue_market` rows only.

Default filter:

- quote = `EUR`
- `is_tradeable = true` if present
- already-added rows hidden by default unless they are already active account coins

Default inserted values:

- `is_visible = true`
- `is_candidate_enabled = true`
- `is_order_proposal_enabled = false`
- `is_hidden = false`
- `source = MANUAL_ADD`

## UI-prep only

No public unauthenticated mutation endpoint is added in this batch.

The renderer exposes prepared action metadata only:

- `action_id`
- `label`
- `enabled=false`
- `reason="UI_PREP_ONLY_NO_AUTH_LAYER"`
- `target_market`
- `target_profile`

These are dashboard/UI-prep descriptors only, not live public mutation handlers.

The wallet dashboard render exposes these datasets inside `wallet.json` and as disabled controls/sections in `wallet.html`.

## Filtering semantics

### Relevant view

- include visible, non-hidden account assets
- include wallet/open-order active assets even if disabled
- exclude hidden assets

### All / Settings view

- include hidden assets
- include disabled assets
- include already-added rows
- include addable Bitvavo EUR markets

### Open Orders Monitor

- disabled candidates still appear if an open order snapshot exists

## Non-goals in this batch

- no profit-plan proposal wiring
- no advice generation wiring
- no order proposal generation
- no public auth layer
- no web mutation endpoint
