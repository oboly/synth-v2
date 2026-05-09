# Synth gurkDB Migration Status

Date: 2026-05-09  
Status: core migration completed, runtime not enabled.

## Summary

The `synth` operational database has been migrated from the Odroid source DB to gurkDB.

The new target database is running on:

- host: `gurkdb`
- IP: `192.168.1.221`
- MariaDB datadir: `/Data/mariadb/`
- database: `synth`
- application user: `synth`
- access scope: localhost, `127.0.0.1`, `192.168.1.%`, and exact lapgurk host `192.168.1.65`

Verified chain:

    lapgurk
    -> ssh gurkdb
    -> ~/projects/synth-v2
    -> .venv
    -> .env
    -> MariaDB gurkDB:/Data/mariadb
    -> migrated synth data
    -> restored v_signal_rule_state_latest
    -> read-only live advice report

## Verified row counts

These counts matched the Odroid source after migration:

| Table | Rows |
|---|---:|
| asset | 41 |
| feat_candle | 1,595,346 |
| advice_state | 1,588,253 |
| asset_interval_quality | 17,706 |
| execution_zone_context | 41 |
| decision_state | 339 |
| execution_intent | 409 |
| asset_profile_snapshot | 41 |
| breathline_token_snapshot | 360 |

## Verified read-only runtime

The following command succeeded on gurkDB:

    python -m src.reporting.run_live_advice_report_extended --venue bitvavo --limit 5

The report returned migrated data and confirmed the required HTF override view path works.

## Restored view

Only this view was restored after base migration:

    v_signal_rule_state_latest

The original source dump had a definer mismatch:

    theone@192.168.1.%

The view was re-imported on gurkDB with local definer:

    root@localhost

## Intentionally not migrated yet

The following were not migrated or enabled yet:

- `synth_bt`
- most historical/research views
- cron chains
- runtime writers
- ETL writers
- signal/advice/ranking writers
- execution/planner/decision runtime
- live trading

## Source DB status

The Odroid source DB was left in:

    read_only = ON

Do not disable this until gurkDB runtime cutover is deliberately approved.

## AppArmor status

MariaDB AppArmor on gurkDB is currently left in complain mode.

Reason: enforcing AppArmor blocked writes/shutdown operations on `/Data/mariadb`.

This should be cleaned up later, but not during migration/import.

## Current repo/runtime status

- lapgurk repo: `cc599bf`
- gurkDB repo: `cc599bf`
- lapgurk `.env`: points to gurkDB
- gurkDB `.env`: points to gurkDB
- gurkDB venv: created and dependencies installed
- DB password secret copied to lapgurk and gurkDB
- dirty bounded 1h chain/feature changes were stashed before migration continuation

Relevant stash on lapgurk:

    stash@{0}: On main: wip bounded 1h chain and feature write window before gurkdb migration

## Next recommended actions

1. Keep Odroid source DB read-only.
2. Decide whether `synth_bt` is needed on gurkDB.
3. Restore additional views only when needed by a concrete command.
4. Build a controlled runtime/cron plan.
5. Do not start writers until the runtime plan is reviewed.
