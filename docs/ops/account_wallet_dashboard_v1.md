# Account Wallet Dashboard V1

## Purpose

`account_wallet_dashboard_v1` renders per-account wallet pages from DB snapshots.

Truth model:

- DB is source of truth
- `/var/www/html/synth/accounts/<profile>/` is static render output only
- no account state is stored in web folders
- credentials remain outside the repo and outside webroot

## Dependency

This dashboard depends on `src/account/run_account_wallet_refresh_v1.py` already existing and writing account-specific rows to:

- `trading_account_balance_snapshot`
- `account_open_order_snapshot`
- `account_asset`

## Files

| File | Role |
|------|------|
| `src/reporting/account_wallet_dashboard_v1.py` | Read-only DB loader + HTML/JSON renderer |
| `src/reporting/run_account_wallet_dashboard_v1.py` | CLI runner |
| `scripts/odroid/run_account_wallet_refresh_once.sh` | Per-profile refresh wrapper |
| `scripts/odroid/run_account_wallet_dashboard_render_once.sh` | Per-profile dashboard render wrapper |
| `docs/ops/systemd/synth-account-wallet-refresh@.service` | Template service example |
| `docs/ops/systemd/synth-account-wallet-refresh@.timer` | Template timer example |
| `docs/ops/systemd/synth-account-wallet-dashboard@.service` | Template service example |
| `docs/ops/systemd/synth-account-wallet-dashboard@.timer` | Template timer example |

## Output paths

Default outputs:

- `/var/www/html/synth/accounts/hugo/wallet.html`
- `/var/www/html/synth/accounts/hugo/wallet.json`
- `/var/www/html/synth/accounts/joost/wallet.html`
- `/var/www/html/synth/accounts/joost/wallet.json`

## What the page shows

- account/profile name
- latest wallet refresh timestamp
- freshness: `FRESH`, `STALE`, `NEVER_REFRESHED`
- balances:
  - asset
  - available
  - in order
  - estimated EUR value if price exists
- open order count by market
- total estimated portfolio value if prices exist
- `account_asset` settings summary:
  - visible
  - candidate enabled
  - proposal enabled
  - hidden / disabled
- warning for stale or missing market data
- management / settings UI-prep sections:
  - addable markets
  - relevant assets
  - all/settings assets
  - disabled action controls for `Add asset`, `Hide`, `Disable`, `Pause 24h`, `Re-enable`

## Management payload

Wallet JSON now includes a read-only `management` section:

- `management.relevant_assets`
- `management.all_assets`
- `management.addable_markets`
- `management.open_orders_monitor`
- `management.actions`

All actions are UI-prep only:

- `enabled=false`
- `reason=UI_PREP_ONLY_NO_AUTH_LAYER`

No public mutation endpoint is enabled by the dashboard render.

Refresh button behavior:

- no active public refresh endpoint
- disabled placeholder only:
  - `Manual refresh requires authenticated account action.`

## Usage

Render Joost:

```bash
python -m src.reporting.run_account_wallet_dashboard_v1 \
  --account-profile joost \
  --venue bitvavo \
  --output-root /var/www/html/synth \
  --output summary
```

Render Hugo:

```bash
python -m src.reporting.run_account_wallet_dashboard_v1 \
  --account-profile hugo \
  --venue bitvavo \
  --output-root /var/www/html/synth \
  --output summary
```

## Safety

Dashboard render is DB-read-only.

Required safety markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

The wallet refresh runner remains private read-only only:

```text
broker_writes=0
order_submission=0
executor=none
```

## Odroid cadence

Recommended timer cadence:

- wallet refresh every 5 minutes
- wallet dashboard render every 5 minutes

Do not auto-install timers from the repo.
