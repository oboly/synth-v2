# Joost Bitvavo credential migration — profile-env → encrypted DB

## Purpose

Migrate Joost's Bitvavo API credentials from the legacy profile-env path
(`~/.config/synth/accounts/joost.env`) to the same encrypted DB storage
used by Hugo (`trading_account_credential` table, AESGCM-256).

After migration the systemd drop-in that forces `credential_source=profile-env`
is removed and Joost uses the default `credential_source=db` path.

## Prerequisites

- `SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY` is set (loaded from `/home/theone/.config/synth/web-auth.env`).
- The profile-account link already exists (verified: `discover_active_linked_profiles` returns `joost`).
- No active credential already exists for Joost in DB (the migration tool checks and refuses to duplicate).

## Step 1 — Dry run (no DB write, no credential prompt)

```bash
cd ~/projects/synth-v2
source .venv/bin/activate
python -m src.account_provisioning.run_migrate_credential_to_db_v1 \
    --profile joost \
    --venue bitvavo \
    --dry-run
```

Expected output:

```
dry_run=ok account_code=bitvavo_joost_read
trading_account_id=<id>
venue=bitvavo
No DB writes (dry run). Ready to migrate.
```

If this fails with `NO_ACTIVE_PRIMARY_LINK`, run the link tool first:

```bash
python -m src.account.run_app_profile_trading_account_link_v1 \
    --profile joost \
    --venue bitvavo \
    --account-code bitvavo_joost_read \
    --set-primary \
    --output summary
```

## Step 2 — Migrate credentials (interactive, not echoed)

Run on the Odroid or the machine that has `SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY`:

```bash
python -m src.account_provisioning.run_migrate_credential_to_db_v1 \
    --profile joost \
    --venue bitvavo
```

You will be prompted for:

```
Bitvavo API key: <not echoed>
Bitvavo API secret: <not echoed>
```

Enter the credentials from `~/.config/synth/accounts/joost.env` (`BITVAVO_API_KEY` and `BITVAVO_API_SECRET`).

Expected output on success:

```
migration=ok account_code=bitvavo_joost_read
trading_account_id=<id>
venue=bitvavo
credential_fingerprint_prefix=<8 hex chars>...
validation_state=UNVALIDATED (will be confirmed on first wallet refresh)
```

## Step 3 — Remove the profile-env systemd drop-in

```bash
rm -rf ~/.config/systemd/user/synth-account-wallet-refresh@joost.service.d/
systemctl --user daemon-reload
```

Verify the drop-in is gone:

```bash
systemctl --user cat synth-account-wallet-refresh@joost.service
```

The output should show only the base unit — no `credential_source=profile-env` override.

## Step 4 — Test wallet refresh

```bash
bash ~/projects/synth-v2/scripts/odroid/run_account_wallet_refresh_once.sh joost
```

Expected: `credential_source=db` in the output, balance snapshot written, no error.

## Step 5 — Full dashboard pipeline smoke test

```bash
bash ~/projects/synth-v2/scripts/odroid/run_linked_profile_dashboard_refresh_once.sh
```

Expected: `linked_profile_count=2 success=2 failure=0`

## Step 6 — Retain or archive the legacy env file

The file `~/.config/synth/accounts/joost.env` is no longer read by any automated runner
after the drop-in is removed. Keep it as a backup until the first successful wallet
refresh confirms the DB credential works, then remove or archive it:

```bash
# Optional — archive for one cycle before deleting
mv ~/.config/synth/accounts/joost.env ~/.config/synth/accounts/joost.env.migrated
```

## Safety markers

```
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```
