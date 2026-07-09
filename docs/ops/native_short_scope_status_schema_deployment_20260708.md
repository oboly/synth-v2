# Native SHORT scope-status schema deployment evidence — 2026-07-08

## Status

Native SHORT A1/A1b scope-status schema deployment completed and the post-schema A3 BTC health smoke passed.

This record is operational evidence only. It does not authorize runtime-owner work.

## Approved code reference

- Approved commit: `f269682e0946c1cd7ba948cb01dbadbfb732ae0f`
- Commit context: PR #63 / A3 health report consumes canonical `native_short_scope_status_v1`

## Migration inputs

### A1

- File: `db/migrations/20260706_native_short_scope_status_persistence_v1.sql`
- SHA256: `c65f8463049ac9d4fad12f96e9b7255ba0cf185dff23832c06d9f75e938719fb`
- Applied: YES

### A1b

- File: `db/migrations/20260707_native_short_cadence_unavailable_v1.sql`
- SHA256: `5fa7447076c112351ccd466854b8972d229e0f2c42e3f3092e991f988dbf5dfc`
- Applied: YES

## Backup evidence

- Backup artifact: `/home/gurk/operator_backups/synth_mariadb/synth_mariadb_logical_backup_20260708T123025Z.sql.gz`
- Size bytes: `596143485`
- SHA256: `d131206e08fb95fc757dec2c821ad27a1961acc6fd32ba8b69f767e1458fd70b`
- Backup evidence UTC: `2026-07-08T12:30:25Z`
- Integrity check: `pigz -t` PASS

## DB-host disk evidence

- Filesystem: `/dev/sda1`
- Mount: `/Data`
- Total: `220G`
- Used: `7.8G`
- Available: `201G`
- Used percent: `4%`
- Disk evidence UTC: `2026-07-08T02:26:30Z`

## DDL execution evidence

- Evidence directory: `/tmp/synth_native_short_a1_a1b_migration_native_short_a1_a1b_20260708T140948Z`
- A1 applied: YES
- A1b applied: YES
- Schema acceptance: PASS
- Re-running A1/A1b is prohibited unless a separate forward-fix or restore plan is explicitly approved.

## Schema acceptance result

The configured `synth` database now contains the Native SHORT A1/A1b scope-status schema.

Required A1/A1b tables:

- `native_short_materializer_run_v1`
- `native_short_scope_observation_v1`
- `native_short_scope_status_v1`
- `native_short_scope_cadence_config_v1`
- `native_short_scope_support_event_v1`

Acceptance summary:

- Required tables exist: PASS
- `native_short_scope_status_v1` full canonical scope-key uniqueness verified: PASS
- A1 support-event backfill verified against preflight source-scope count: PASS
- A1b configuration-unavailable contract verified: PASS
- Existing native map-ledger table fingerprints unchanged: PASS

## Post-schema A3 BTC health smoke

Scope:

- venue: `bitvavo`
- symbol: `BTC`
- quote_currency: `EUR`
- fib_trading_horizon: `SHORT`
- primary_interval: `4h`
- supporting_interval: `1h`

Command:

`python -m src.reporting.run_native_short_map_ledger_health_report_v1 --venue bitvavo --symbols BTC --quote-currency EUR --fib-trading-horizon SHORT --primary-interval 4h --supporting-interval 1h --output jsonl`

Result:

- Exit code: `0`
- Scope row count: `1`
- Scope status: `SUPPORTED`
- Scope support state: `SUPPORTED`
- Projection row count: `0`
- Projection status: `MISSING`
- `scope_status_code`: `null`
- `scope_status_reason_code`: `null`
- `map_lifecycle_state`: `null`
- `observation_freshness_state`: `null`
- `source_freshness_state`: `null`
- `actionability_state`: `null`
- `overall_health_status`: `NEEDS_REVIEW`
- `overall_health_reason_codes`: `["PROJECTION_ROW_MISSING"]`
- A3 BTC smoke result: PASS

Interpretation:

The report now reaches the canonical projection table and truthfully reports the missing projection row. It does not fail because of missing schema and does not fabricate a healthy state from lower-level map ledger data.

## Safety markers

- `db_writes=0`
- `broker_private_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `live_orders=0`
- `decision_gate=none`
- `execution_planner=none`
- `executor=none`

No migration, DDL, materializer, cadence seeding, scope seeding, broker, timer, service, repo, docs, or GitHub action was performed during the post-schema A3 BTC smoke.

## Remaining blocker

PR B remains blocked.

Remaining required acceptance before PR B may be reconsidered:

- P0-A host operational acceptance must be separately completed.

This schema deployment and A3 smoke do not prove materializer readiness, runtime-owner readiness, timer safety, broker safety, or execution readiness.
