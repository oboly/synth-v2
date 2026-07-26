# Synth Chain 4h Database Least-Privilege Contract v1

## Decision

```text
capability=native_short_4h_chain
database_identity=synth_chain_4h_writer@192.168.1.%
database=synth
authority_scope=exact_object_grants_only
schema_wildcards=forbidden
administrative_privileges=forbidden
existing_synth_identity=unchanged
ownership=UNASSIGNED
production_activation=NOT_AUTHORIZED
```

This is the database identity for the complete market-only
`scripts/run_chain_4h.sh` processing chain. It is not a Native-SHORT-tables-only
identity. The exact grant truth is owned by
`src/operations/synth_chain_4h_db_authority_v1.py`.

The repository artifact does not create the identity, change credentials,
execute grants, select a runtime owner, invoke the writer, publish Native SHORT
state, or authorize activation.

## Semantic Boundary

The chain is market-only and account-agnostic. It may read and write public
market observations, deterministic features, signals, market ranking and
selection, market setup-filter and paper-advice observations, Native SHORT
market state, and market-chain runtime metadata.

`execution_zone_context` is allowed because repository ownership and data flow
make it market-derived zone context:

```text
src.zone.run_zone_engine_v1
-> deterministic public-candle zone calculation
-> execution_zone_context
-> read-only paper-advice context
```

It is not `decision_gate` permission, execution-planner intent, an execution
plan, executor state, an order, a fill, or broker state. This classification is
semantic and explicit; it is not inferred from the word `execution`.

The identity has no authority over account/profile state, balances, positions,
wallets, credentials, broker/private API state, decision-gate state,
execution-planner intent, executor state, orders, fills, or broker-write
tables.

## Complete Runtime Call Graph

The committed service path is:

```text
deploy/systemd/synth-chain-4h.service
-> ExecStartPre:
   src.operations.run_synth_chain_4h_db_environment_preflight_v1
   (closed binding/secret-file/repository-unit checks; SQL=none)
-> ExecStartPre:
   src.operations.run_synth_chain_4h_db_grant_preflight_v1
   (read-only authenticated/grant identity and exact-grant checks)
-> ExecStartPre:
   src.operations.verify_writer_capability_authorization_v1
   (repository/authorization checks; SQL=none)
-> ExecStart:
   scripts/run_chain_4h.sh
   -> src.operations.run_synth_chain_4h_db_environment_preflight_v1
      (same closed binding check before every DB-capable child; SQL=none)
   -> src.operations.run_synth_chain_4h_db_grant_preflight_v1
      (same read-only grant contract; no DDL or DML)
   -> src.operations.verify_writer_capability_authorization_v1
      (SQL=none)
   -> src.market_data.native_short_repository_source_identity_v1
      (SQL=none)
   -> src.operations.run_persisted_market_price_freshness_v1
      -> src.operations.persisted_market_price_freshness_v1
   -> src.operations.run_persisted_market_candle_freshness_v1
      -> src.operations.persisted_market_candle_freshness_v1
   -> scripts/run_native_short_scope_status_chain_once.sh
      -> src.operations.verify_writer_capability_authorization_v1
         (SQL=none)
      -> src.market_data.run_native_short_scope_status_chain_v1
         -> src.market_data.native_short_writer_commit_fence_v1
         -> src.market_data.native_short_scope_status_materializer_v1
            -> src.market_data.native_short_map_materializer_v1
            -> src.market_data.native_short_map_level_status_materializer_v1
               -> src.market_data.native_short_map_level_status_v1
               -> src.market_rules.price_tick_normalization_v1
   -> src.market_data.run_native_short_fib_context_snapshot_v1
      -> src.market_data.native_short_fib_context_snapshot_v1
   -> src.features.run_feat_candle
      -> src.features.etl_candle_feat
   -> src.signal_engine.run_signal_state_etl
      -> src.engine.write_signal_engine_state
   -> src.advice.run_advice_engine
   -> src.ranking.run_ranking_engine
   -> src.measurement.run_asset_interval_quality_snapshot
   -> src.selection.run_selection_engine_v2
   -> src.zone.run_zone_engine_v1
      -> src.zone.repository
   -> src.trade_setup_filter.run_trade_setup_filter_v1
      -> src.trade_setup_filter.repository
      -> src.trade_setup_filter.observation_repository
   -> src.research.run_trade_setup_filter_policy_preview_v1
   -> src.advice.run_paper_advice_policy_v1
   -> src.strategy_runtime.run_strategy_runtime_snapshot
      -> src.strategy_runtime.runtime_snapshot_writer
```

Pure calculation/configuration imports below those modules execute no SQL and
add no authority.

Every SQL-capable path in this graph obtains its connection through:

```text
src.common.db
-> src.common.db_core_v1.get_connection
-> pymysql.connect
```

Some runners call `load_dotenv()` themselves and importing `src.common.db`
also calls it. These calls use the default `override=False` behavior. Before
this binding, the final generic resolution was:

```text
host     = DB_HOST -> MYSQL_HOST -> localhost
port     = DB_PORT -> MYSQL_PORT -> 3306
user     = DB_USER -> MYSQL_USER -> synth
password = DB_PASSWORD -> MYSQL_PASSWORD -> empty
database = explicit argument -> DB_NAME -> MYSQL_DATABASE -> synth
```

The service did not inject an `EnvironmentFile`, so its children could read
the checkout `.env` from the fixed working directory. A checkout containing
the broad `DB_USER=synth` identity therefore selected that identity, while a
checkout with no matching value used the same `synth` default. Children
loaded dotenv at different points, but all database-capable children converged
on the same generic helper and could silently use the broad identity.

## Closed Runtime Binding

The shared DB helper now has one explicit closed profile:

```text
SYNTH_DB_BINDING_PROFILE=synth_chain_4h
SYNTH_CHAIN_4H_DB_HOST=gurkdb
SYNTH_CHAIN_4H_DB_PORT=3306
SYNTH_CHAIN_4H_DB_USER=synth_chain_4h_writer
SYNTH_CHAIN_4H_DB_NAME=synth
SYNTH_CHAIN_4H_DB_PASSWORD_FILE=/etc/synth/synth-chain-4h-db-password-v1
```

Only the canonical service supplies this profile, and normal process
inheritance carries the exact non-secret values to its children. No
service-name guessing or process-global environment mutation is used.
`src.common.db_core_v1` retains its existing generic resolution when the
profile and all dedicated variables are absent. If the profile or any
dedicated variable is present, the closed resolver must succeed; it never
falls back.

Under the closed profile, host and port are explicit, username and database
must equal the values above, generic `DB_*` and `MYSQL_*` values are ignored,
and a database override other than `synth` is rejected before connection.
Charset, collation, and timeouts use fixed connection constants rather than
generic `.env` values.

The password file contract is:

```text
path=/etc/synth/synth-chain-4h-db-password-v1
owner=root
group=gurk
mode=0640
type=regular
symlink=forbidden
payload=one non-empty UTF-8 password value with one optional trailing newline
```

The file remains external to Git. The resolver opens it with no-follow and
close-on-exec semantics, compares the opened inode to the inspected inode,
checks exact owner/group/mode, bounds its size, and rejects missing, empty,
symlinked, non-regular, changed, over-permissive, wrongly owned, multiline, or
NUL-containing content. Password material is held only in process memory for
the PyMySQL call and is never placed in the unit, argv, log output, exception
text, fixture, DSN, fingerprint, or process title.

## Executed SQL Inventory

Each row is one distinct SQL execution site or one repeated parameterization of
the same site. `UPSERT` means `INSERT ... ON DUPLICATE KEY UPDATE`.

| Chain step | SQL statement | Source |
|---|---|---|
| price freshness | `START TRANSACTION READ ONLY` | `src/operations/run_persisted_market_price_freshness_v1.py:81` |
| price freshness | `SELECT` latest rows from `market_price_snapshot` | `src/operations/persisted_market_price_freshness_v1.py:45-62` |
| candle freshness | `START TRANSACTION READ ONLY` | `src/operations/run_persisted_market_candle_freshness_v1.py:76` |
| candle freshness | `SELECT` latest close from `obs_market_candle` | `src/operations/persisted_market_candle_freshness_v1.py:36-55` |
| Native SHORT scope selection | `SELECT` supported rows from `native_short_map_scope_v1` | `src/market_data/run_native_short_scope_status_chain_v1.py:200-236` |
| Native SHORT candles | `SELECT` from `obs_market_candle JOIN asset`, parameterized once per interval/scope | `src/market_data/run_native_short_scope_status_chain_v1.py:262-283` |
| writer commit fence | `SELECT ... FOR UPDATE` from `native_short_map_scope_v1`, captured and revalidated | `src/market_data/native_short_writer_commit_fence_v1.py:76-103` |
| writer commit fence | `SELECT ... FOR UPDATE` from `native_short_scope_cadence_config_v1`, captured and revalidated | `src/market_data/native_short_writer_commit_fence_v1.py:107-145` |
| scope projection facts | `SELECT` from `native_short_scope_support_event_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:435-443` |
| scope projection facts | `SELECT` from `native_short_scope_cadence_config_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:455-465` |
| scope projection facts | `SELECT` from `native_short_scope_observation_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:482-490` |
| materializer run | `INSERT` into `native_short_materializer_run_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:544-590` |
| materializer run | compare-and-set `UPDATE` of `native_short_materializer_run_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:597-634` |
| scope observation | `INSERT` into `native_short_scope_observation_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:641-714` |
| lifecycle transition | `INSERT` into `native_short_map_lifecycle_event_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:721-746` |
| scope projection | `UPSERT` `native_short_scope_status_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:753-830` |
| map scope | `SELECT` from `native_short_map_scope_v1` | `src/market_data/native_short_map_materializer_v1.py:192-219` |
| map scope lock | `SELECT ... FOR UPDATE` from `native_short_map_scope_v1` | `src/market_data/native_short_map_materializer_v1.py:240-261` |
| map facts | `SELECT` from `native_short_map_v1` | `src/market_data/native_short_map_materializer_v1.py:328-368` |
| generation facts | `SELECT` from `native_short_map_generation_event_v1` | `src/market_data/native_short_map_materializer_v1.py:416-450` |
| lifecycle facts | `SELECT` from `native_short_map_lifecycle_event_v1` | `src/market_data/native_short_map_materializer_v1.py:496-518` |
| generation event | `INSERT` into `native_short_map_generation_event_v1` | `src/market_data/native_short_map_materializer_v1.py:626-666` |
| immutable map | `INSERT` into `native_short_map_v1` | `src/market_data/native_short_map_materializer_v1.py:758-804` |
| supersession event | `INSERT` into `native_short_map_lifecycle_event_v1` | `src/market_data/native_short_map_materializer_v1.py:855-874` |
| level projection | `SELECT` from `native_short_scope_status_v1` | `src/market_data/native_short_map_level_status_materializer_v1.py:360-393` |
| level geometry | `SELECT` from `native_short_map_v1` | `src/market_data/native_short_map_level_status_materializer_v1.py:426-462` |
| level candles | `SELECT` from `obs_market_candle JOIN asset` | `src/market_data/native_short_map_level_status_materializer_v1.py:500-510` |
| tick rule | `SELECT` from `venue_market` | `src/market_rules/price_tick_normalization_v1.py:199-224` |
| level replacement | `DELETE` from `native_short_map_level_status_v1` | `src/market_data/native_short_map_level_status_v1.py:420-451` |
| level replacement | `INSERT` into `native_short_map_level_status_v1` | `src/market_data/native_short_map_level_status_v1.py:454-529` |
| snapshot scope | `SELECT` from `native_short_map_scope_v1 LEFT JOIN native_short_scope_status_v1` | `src/market_data/native_short_fib_context_snapshot_v1.py:868-884` |
| snapshot map | `SELECT` from `native_short_scope_status_v1 JOIN native_short_map_v1` | `src/market_data/native_short_fib_context_snapshot_v1.py:886-905` |
| snapshot levels | `SELECT` from `native_short_scope_status_v1 JOIN native_short_map_level_status_v1` | `src/market_data/native_short_fib_context_snapshot_v1.py:907-923` |
| snapshot generation | `SELECT` from `native_short_scope_status_v1 JOIN native_short_map_generation_event_v1` | `src/market_data/native_short_fib_context_snapshot_v1.py:925-936` |
| snapshot lifecycle | `SELECT` from `native_short_scope_status_v1 JOIN native_short_map_lifecycle_event_v1` | `src/market_data/native_short_fib_context_snapshot_v1.py:938-947` |
| candle features | `SELECT` from `asset`; `SELECT` from `obs_market_candle`; `UPSERT` `feat_candle` | `src/features/etl_candle_feat.py:57-67,92-135,318-393` |
| signal state | two `SELECT` statements from `feat_candle JOIN asset`; `UPSERT` `signal_engine_state` | `src/signal_engine/run_signal_state_etl.py:42-143`; `src/engine/write_signal_engine_state.py:51-180` |
| advice state | three `SELECT` statements from `signal_engine_state`/`asset`; `UPSERT` `advice_state` | `src/advice/run_advice_engine.py:152-276,295-340` |
| ranking state | three `SELECT` statements from `signal_engine_state`/`asset`/`advice_state`; `UPSERT` `ranking_state` | `src/ranking/run_ranking_engine.py:37-198,345-401` |
| quality snapshot | `SELECT` from `v_asset_interval_quality_v3`; `UPSERT` `asset_interval_quality` | `src/measurement/run_asset_interval_quality_snapshot.py:29-54,57-147` |
| selection state | `SELECT` from `asset_interval_quality`/`signal_engine_state`/`asset`; `UPSERT` `selection_state` | `src/selection/run_selection_engine_v2.py:61-179,369-433` |
| zone context | `SELECT` from `asset`; `SELECT` from `obs_market_candle` | `src/zone/repository.py:26-101` |
| zone context | `UPSERT` `fib_observation_v2`; `UPSERT` `zone_observation_v2` | `src/zone/repository.py:107-278` |
| zone context | `DELETE` then `UPSERT` `execution_zone_context` | `src/zone/repository.py:291-401` |
| setup filter | `SELECT` from `selection_state`/`asset`/`obs_market_candle` | `src/trade_setup_filter/repository.py:30-141` |
| setup filter metadata | `SELECT` from `information_schema.tables` | `src/trade_setup_filter/observation_repository.py:29-48` |
| setup filter observation | `UPSERT` `trade_setup_filter_observation` | `src/trade_setup_filter/observation_repository.py:82-151` |
| policy preview | two `SELECT` statements from `trade_setup_filter_observation`; `UPSERT` `trade_setup_policy_preview_observation` | `src/research/run_trade_setup_filter_policy_preview_v1.py:170-244,457-550` |
| paper advice A+ | `SELECT` from `aplus_table1_report`; `SELECT` from `aplus_table1_row` | `src/advice/run_paper_advice_policy_v1.py:47-97` |
| paper advice inputs | `SELECT` from `selection_state`, filter/policy observations, `execution_zone_context`, `asset`, and `vw_paper_advice_execution_zone_context_v1` | `src/advice/run_paper_advice_policy_v1.py:167-286` |
| paper advice observation | `UPSERT` `paper_advice_observation` | `src/advice/run_paper_advice_policy_v1.py:391-452` |
| runtime metadata | `INSERT` `strategy_runtime_snapshot`; `INSERT` `strategy_runtime_component` | `src/strategy_runtime/runtime_snapshot_writer.py:195-280` |

`information_schema.tables` visibility follows the identity's object
privileges and receives no explicit grant. `START TRANSACTION`, `COMMIT`,
`ROLLBACK`, `LAST_INSERT_ID`, connection `SET NAMES`, and row-level
`SELECT ... FOR UPDATE` require no additional grant. The graph uses no
temporary tables, named locks, `LOCK TABLES`, stored routines, external
sequences, DDL, or administrative statements.

## Exact Object-Level Privilege Matrix

| Object | SELECT | INSERT | UPDATE | DELETE | Static proof |
|---|:---:|:---:|:---:|:---:|---|
| `advice_state` | yes | yes | yes | no | advice upsert; ranking read |
| `aplus_table1_report` | yes | no | no | no | paper-advice A+ read |
| `aplus_table1_row` | yes | no | no | no | paper-advice A+ read |
| `asset` | yes | no | no | no | feature/signal/advice/ranking/selection/zone/filter reads |
| `asset_interval_quality` | yes | yes | yes | no | quality upsert; selection read |
| `execution_zone_context` | yes | yes | yes | yes | zone replacement; paper-advice read |
| `feat_candle` | yes | yes | yes | no | feature upsert; signal read |
| `fib_observation_v2` | no | yes | yes | no | zone upsert |
| `market_price_snapshot` | yes | no | no | no | freshness read |
| `native_short_map_generation_event_v1` | yes | yes | no | no | Native SHORT ledger/snapshot |
| `native_short_map_level_status_v1` | yes | yes | no | yes | projection replacement/snapshot |
| `native_short_map_lifecycle_event_v1` | yes | yes | no | no | Native SHORT ledger/snapshot |
| `native_short_map_scope_v1` | yes | no | no | no | scope selection and row lock |
| `native_short_map_v1` | yes | yes | no | no | map materialization/snapshot |
| `native_short_materializer_run_v1` | no | yes | yes | no | run insert/terminalize |
| `native_short_scope_cadence_config_v1` | yes | no | no | no | cadence fact and row lock |
| `native_short_scope_observation_v1` | yes | yes | no | no | observation fact/append |
| `native_short_scope_status_v1` | yes | yes | yes | no | projection upsert/read |
| `native_short_scope_support_event_v1` | yes | no | no | no | support fact read |
| `obs_market_candle` | yes | no | no | no | freshness/features/Native SHORT/zone/filter reads |
| `paper_advice_observation` | no | yes | yes | no | paper-advice upsert |
| `ranking_state` | no | yes | yes | no | ranking upsert |
| `selection_state` | yes | yes | yes | no | selection upsert; filter/advice reads |
| `signal_engine_state` | yes | yes | yes | no | signal upsert; advice/ranking/selection reads |
| `strategy_runtime_component` | no | yes | no | no | runtime metadata append |
| `strategy_runtime_snapshot` | no | yes | no | no | runtime metadata append |
| `trade_setup_filter_observation` | yes | yes | yes | no | filter upsert; policy/advice reads |
| `trade_setup_policy_preview_observation` | yes | yes | yes | no | policy upsert; advice read |
| `v_asset_interval_quality_v3` | yes | no | no | no | quality view read |
| `venue_market` | yes | no | no | no | public tick precision read |
| `vw_paper_advice_execution_zone_context_v1` | yes | no | no | no | paper-advice zone view read |
| `zone_observation_v2` | no | yes | yes | no | zone upsert |

No table-level `CREATE`, `ALTER`, `DROP`, `INDEX`, `REFERENCES`, `TRIGGER`,
`EXECUTE`, `LOCK TABLES`, or `GRANT OPTION` is required.

## DBA Artifact

Canonical artifact:

```text
db/dba/synth_chain_4h_writer_v1.sql
```

It acts only on
`'synth_chain_4h_writer'@'192.168.1.%'`, clears only that dedicated identity's
prior grants, and applies the exact matrix. It does not revoke or alter
`synth@192.168.1.%` or any other identity. Password material must be supplied
separately as the session variable `@synth_chain_4h_writer_password`; the
artifact fails before identity creation if that value is missing or empty and
clears the session variables after use.

The artifact is not a migration and must not be run by application code.

## Read-Only Grant Preflight

Candidate configuration uses only:

```text
SYNTH_DB_BINDING_PROFILE=synth_chain_4h
SYNTH_CHAIN_4H_DB_HOST
SYNTH_CHAIN_4H_DB_PORT
SYNTH_CHAIN_4H_DB_USER=synth_chain_4h_writer
SYNTH_CHAIN_4H_DB_NAME=synth
SYNTH_CHAIN_4H_DB_PASSWORD_FILE
```

The grant preflight uses the same closed resolver and external secret file as
the runtime. It does not read `.env`, `DB_*`, or `MYSQL_*` fallbacks:

```bash
python -m src.operations.run_synth_chain_4h_db_grant_preflight_v1
```

It executes only:

```text
START TRANSACTION READ ONLY
SELECT USER(), CURRENT_USER(), DATABASE()
SHOW GRANTS
ROLLBACK
```

The repository/host binding preflight is:

```bash
python -m src.operations.run_synth_chain_4h_db_environment_preflight_v1
```

It performs no SQL. It reports the active profile, non-secret endpoint, port,
username, database, secret path/type/owner/group/mode/symlink state, generic
fallback-variable names and their ignored status, repository-unit equivalence,
and whether the grant preflight resolves the exact same candidate
configuration. The existing installed-unit equivalence preflight remains the
owner of repository-versus-installed systemd content and inactive-state checks.

The grant preflight reports authenticated and matched grant identities without
printing the configured password, DSN, token, raw grants, password hash, or
credential fingerprint. It fails on missing privileges, additional object
privileges, schema/global wildcards, administrative authority, grant option,
foreign-database authority, account/credential/decision/planner/executor/order
authority, an unexpected identity, or an unexpected database.

Passing this repository preflight proves only candidate grant truth. It does
not prove installed service configuration, assign ownership, authorize a
writer run, publish state, or authorize timer activation.

## Safety State

```text
database_mutations=0
credential_material_changed=0
host_mutations=0
systemd_mutations=0
writer_invocations=0
canonical_publication=0
ownership=UNASSIGNED
activation_authorized=NO
broker_private_calls=0
broker_writes=0
order_submission=0
```
