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

## AppArmor cleanup update

Date: 2026-05-09

MariaDB AppArmor was moved from complain mode back to enforce mode.

The active profile is:

    /etc/apparmor.d/mariadbd

The correct local override is:

    /etc/apparmor.d/local/mariadbd

The override allows the dedicated MariaDB datadir on `/Data/mariadb`.

Validation completed:

- controlled DB write smoke passed
- MariaDB restart under AppArmor enforce passed
- MariaDB remained active after restart
- `synth` row checks passed
- `/Data/mariadb` remained active as datadir

Remaining AppArmor DENIED messages for `/sys/devices/.../block/.../dev` were observed during startup, but did not block MariaDB startup, datadir access, writes, or read-only Synth report operation. Treat as non-blocking unless future MariaDB errors appear.

## synth_bt migration update

Date: 2026-05-09

The `synth_bt` database was migrated from Odroid to gurkDB.

Migration method:

- dumped base tables/data from Odroid
- excluded views from the base dump
- dumped views separately
- imported base tables/data into a freshly created `synth_bt` database on gurkDB
- imported views after stripping legacy DEFINER lines

Validation completed on gurkDB:

- checksum verification passed
- `synth_bt` contains 26 objects
- 8 views were imported and tested
- all imported views returned sample counts successfully
- total target size reported approximately 383 MB

The first import attempt failed because the target DB was dropped without recreating/selecting `synth_bt`. This was corrected by explicitly creating `synth_bt` and importing with:

    gzip -dc synth_bt_base.sql.gz | mariadb synth_bt

## Stage 2 controlled ETL write update

Date: 2026-05-09

A controlled single-shot ETL writer test was completed on gurkDB.

Scope:

- asset: BTC
- market: BTC-EUR
- venue: bitvavo
- interval: 1h
- window start: 2026-05-08T05:00:00+00:00
- window end: 2026-05-08T08:00:00+00:00
- writer: `src.etl.bitvavo.run_candles_etl`
- mode: manual, bounded, ETL-only

Dry-run result:

- raw candles fetched: 3
- filtered candles: 3
- written: 0
- row delta: 0

Real write result:

- raw candles fetched: 3
- filtered candles: 3
- ETL reported written: 3
- row delta in `obs_market_candle`: +2
- latest BTC 1h close after test: 2026-05-08 08:00:00

Interpretation:

- The bounded ETL write path works on gurkDB.
- `written=3` with `ROW_DELTA=2` is consistent with one existing candle being upserted and two new candles being inserted.
- No chain, feature writer, signal/advice/ranking writer, decision, execution, or cron runtime was started.

## Stage 3 controlled feature write update

Date: 2026-05-09

A controlled single-shot feature writer test was completed on gurkDB.

Code baseline:

- commit: 45ea1b5
- change: bounded feature write-window support was merged into main
- `run_feat_candle` now supports `--start`, `--end`, `--lookback-hours`, and `--warmup-bars`

Scope:

- asset: BTC
- venue: bitvavo
- interval: 1h
- window start: 2026-05-08T05:00:00+00:00
- window end: 2026-05-08T09:00:00+00:00
- writer: `src.features.run_feat_candle`
- mode: manual, bounded, feature-only
- warmup bars: 300

Result:

- feature writer reported rows: 4
- row delta in `feat_candle`: +3
- latest BTC 1h feature close after test: 2026-05-08 08:00:00

Interpretation:

- The bounded feature write path works on gurkDB.
- `rows=4` with `FEATURE_ROW_DELTA=3` is consistent with one existing feature row being upserted and three new feature rows being inserted.
- No chain, ETL batch beyond the previous Stage 2 test, signal/advice/ranking writer, decision, execution, or cron runtime was started.

## Stage 4a controlled signal engine write update

Date: 2026-05-09

A controlled single-shot signal engine writer test was completed on gurkDB.

Scope:

- asset: BTC
- venue: bitvavo
- interval: 1h
- signal snapshot: 2026-05-08 05:00:00
- writer: `src.signal_engine.run_signal_state_etl`
- mode: manual, latest-snapshot, signal-only

Dry-run result:

- feat rows processed: 1
- written: 0
- row delta: 0

Real write result:

- signal rows written by runner: 1
- row delta in `signal_engine_state`: 0
- latest BTC 1h `created_ts_utc` updated to 2026-05-09 11:49:43

Interpretation:

- The signal engine write path works on gurkDB.
- `ROW_DELTA=0` is consistent with updating/upserting an existing latest signal row.
- No chain, advice/ranking writer, selection writer, decision, execution, or cron runtime was started.

## Stage 4a controlled signal engine write update

Date: 2026-05-09

A controlled single-shot signal engine writer test was completed on gurkDB.

Scope:

- asset: BTC
- venue: bitvavo
- interval: 1h
- signal snapshot: 2026-05-08 05:00:00
- writer: `src.signal_engine.run_signal_state_etl`
- mode: manual, latest-snapshot, signal-only

Dry-run result:

- feat rows processed: 1
- written: 0
- row delta: 0

Real write result:

- signal rows written by runner: 1
- row delta in `signal_engine_state`: 0
- latest BTC 1h `created_ts_utc` updated to 2026-05-09 11:49:43

Interpretation:

- The signal engine write path works on gurkDB.
- `ROW_DELTA=0` is consistent with updating/upserting an existing latest signal row.
- No chain, advice/ranking writer, selection writer, decision, execution, or cron runtime was started.

## Stage 4b controlled advice engine write update

Date: 2026-05-09

A controlled advice engine writer test was completed on gurkDB.

Scope:

- venue: bitvavo
- interval: 1h
- signal snapshot: 2026-05-08 05:00:00
- writer: `src.advice.run_advice_engine`
- mode: manual, latest-snapshot, advice-only

Preflight:

- latest signal snapshot: 2026-05-08 05:00:00
- enabled signal rows at latest snapshot: 37
- advice runner confirmed latest-snapshot only
- advice writer uses `INSERT ... ON DUPLICATE KEY UPDATE`
- no DELETE or historical replay path was used

Real write result:

- advice rows written by runner: 37
- row delta in `advice_state`: 0
- rows at latest advice snapshot after test: 37
- latest advice snapshot remained 2026-05-08 05:00:00

Interpretation:

- The advice engine write path works on gurkDB.
- `ROW_DELTA=0` is consistent with updating/upserting existing latest advice rows.
- `created_ts_utc` did not change because the advice upsert does not update that column.
- No chain, ranking writer, selection writer, decision, execution, or cron runtime was started.

## Stage 4c controlled ranking engine write update

Date: 2026-05-09

A controlled ranking engine writer test was completed on gurkDB.

Scope:

- venue: bitvavo
- interval: 1h
- signal/advice snapshot: 2026-05-08 05:00:00
- writer: `src.ranking.run_ranking_engine`
- mode: manual, latest-snapshot, ranking-only

Preflight:

- latest signal snapshot: 2026-05-08 05:00:00
- enabled signal rows at latest snapshot: 37
- enabled advice rows at latest snapshot: 37
- ranking runner confirmed latest-snapshot only
- ranking writer uses `INSERT ... ON DUPLICATE KEY UPDATE`
- no DELETE or historical replay path was used

Real write result:

- ranking rows written by runner: 37
- row delta in `ranking_state`: 0
- rows at latest ranking snapshot after test: 37
- latest ranking snapshot remained 2026-05-08 05:00:00

Interpretation:

- The ranking engine write path works on gurkDB.
- `ROW_DELTA=0` is consistent with updating/upserting existing latest ranking rows.
- No chain, selection writer, decision, execution, or cron runtime was started.
