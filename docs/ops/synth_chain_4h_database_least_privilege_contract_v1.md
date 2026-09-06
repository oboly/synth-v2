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
         -> src.market_data.native_short_auto_onboarding_v1.reconcile_ready_scopes
            (AUTO_ONBOARD_SCOPES phase; runs unconditionally whenever the
             entrypoint is called with no explicit symbols -- the scheduled
             production path always omits symbols -- before the writer commit
             fence and materializer transaction; see "Native SHORT Scope
             Administration Ledger Gap" below)
            -> src.market_data.native_short_multi_asset_audit_v1.run_audit
            -> src.market_data.native_short_scope_administration_transaction_v1
               .execute_scope_administration
         -> src.market_data.native_short_writer_commit_fence_v1
         -> src.market_data.native_short_scope_status_materializer_v1
            -> src.market_data.native_short_map_materializer_v1
            -> src.market_data.native_short_map_level_status_materializer_v1
               -> src.market_data.native_short_map_level_status_v1
               -> src.market_rules.price_tick_normalization_v1
            -> src.market_data.native_short_map_level_target_event_materializer_v1
               (_append_terminal_target_events terminal-transition hook;
                runs unconditionally on every genuine COMPLETED lifecycle
                transition, before that transition is recorded, in the same
                transaction -- see "Target-Event Coverage Gap" below)
               -> src.market_data.native_short_map_level_target_event_v1
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
| scope admin idempotency read | `SELECT` from `native_short_scope_admin_operation_v1` (unconditional; `read_existing_operation` plus the operations projection in `read_scope_state_snapshot`) | `src/market_data/native_short_scope_administration_transaction_v1.py:680-711,751-772` via `src/market_data/native_short_auto_onboarding_v1.py:36-93` |
| scope admin promote-operation audit read | `SELECT` from `native_short_scope_admin_operation_v1` (`PROMOTE_SCOPE` rows, reachable from every `run_audit` call inside `reconcile_ready_scopes`) | `src/market_data/native_short_multi_asset_audit_v1.py:814-822,830-832` |
| scope admin ledger write | `INSERT` into `native_short_scope_admin_operation_v1` (only when a READY market is actually onboarded to `SUPPORTED`; append-only, never `UPDATE`/`DELETE`) | `src/market_data/native_short_scope_administration_transaction_v1.py:1629-1654` |
| scope onboard: new READY scope | `INSERT` into `native_short_map_scope_v1` (`PROMOTE_NEW`, `classify_scope_state` == `NO_SCOPE`; first row for a canonical scope) | `src/market_data/native_short_scope_administration_transaction_v1.py:1753-1780` via `decide_administration`/`_decide_promote` at `:1301-1349` |
| scope onboard: re-support after withdrawal | `UPDATE` `native_short_map_scope_v1` (`PROMOTE_REACTIVATE`, `classify_scope_state` == `MANAGED_REMOVED`; flips the existing `NOT_APPLICABLE` row back to `SUPPORTED`) | `src/market_data/native_short_scope_administration_transaction_v1.py:1802-1821` via `decide_administration`/`_decide_promote` at `:1301-1349` |
| scope onboard: new cadence row | `INSERT` into `native_short_scope_cadence_config_v1` (`PROMOTE_NEW` and `PROMOTE_REACTIVATE` both call this; one new active cadence row per onboarding/re-support) | `src/market_data/native_short_scope_administration_transaction_v1.py:1875-1917` via `_apply_decision` at `:2009-2048` |
| scope onboard: support event append | `INSERT` into `native_short_scope_support_event_v1` (`PROMOTE_NEW` and `PROMOTE_REACTIVATE` both call this; append-only, never `UPDATE`/`DELETE`) | `src/market_data/native_short_scope_administration_transaction_v1.py:1709-1750` via `_apply_decision` at `:2009-2048` |
| Native SHORT scope selection | `SELECT` supported rows from `native_short_map_scope_v1` | `src/market_data/run_native_short_scope_status_chain_v1.py:200-236` |
| Native SHORT candles | `SELECT` from `obs_market_candle JOIN asset`, parameterized once per interval/scope | `src/market_data/run_native_short_scope_status_chain_v1.py:262-283` |
| writer commit fence | `SELECT ... FOR UPDATE` from `native_short_map_scope_v1`, captured and revalidated | `src/market_data/native_short_writer_commit_fence_v1.py:76-103` |
| writer commit fence | `SELECT ... FOR UPDATE` from `native_short_scope_cadence_config_v1`, captured and revalidated | `src/market_data/native_short_writer_commit_fence_v1.py:107-145` |
| scope projection facts | `SELECT` from `native_short_scope_support_event_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:435-443` |
| scope projection facts | `SELECT` from `native_short_scope_cadence_config_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:455-465` |
| scope projection facts | `SELECT` from `native_short_scope_observation_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:482-490` |
| materializer run | `INSERT` into `native_short_materializer_run_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:544-590` |
| materializer run | compare-and-set `UPDATE ... WHERE run_id = ...` of `native_short_materializer_run_v1` (the `WHERE` clause requires `SELECT` in addition to `UPDATE`) | `src/market_data/native_short_scope_status_materializer_v1.py:597-634` |
| scope observation | `INSERT` into `native_short_scope_observation_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:641-714` |
| lifecycle transition | `INSERT` into `native_short_map_lifecycle_event_v1` | `src/market_data/native_short_scope_status_materializer_v1.py:721-746` |
| terminal target-event coverage | `SELECT` from `native_short_map_level_target_event_coverage_v1` (unconditional on every genuine COMPLETED transition; `establish_or_fetch_target_event_coverage_for_map`'s own `INSERT` branch is not reachable here because this entrypoint never supplies a non-`None` watermark) | `src/market_data/native_short_map_level_target_event_v1.py:411-447` via `src/market_data/native_short_scope_status_materializer_v1.py:899-947` |
| terminal target events | `SELECT` from `native_short_map_level_target_event_v1`; `INSERT` into `native_short_map_level_target_event_v1` (both reached only when a coverage row already exists for the map, e.g. established by an earlier standalone run under a different identity) | `src/market_data/native_short_map_level_target_event_v1.py:560-634` via `src/market_data/native_short_map_level_target_event_materializer_v1.py:238-361` |
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
| ranking state | three `SELECT` statements from `signal_engine_state`/`asset`/`advice_state`; `INSERT ... ON DUPLICATE KEY UPDATE` `ranking_state` (requires `SELECT` on the target table) | `src/ranking/run_ranking_engine.py:37-198,345-401` |
| quality snapshot | exact-key bounded `SELECT` from `asset` + `obs_market_candle`; `UPSERT` `asset_interval_quality` | `src/measurement/run_asset_interval_quality_snapshot.py` |
| selection state | `SELECT` from `asset_interval_quality`/`signal_engine_state`/`asset`; `UPSERT` `selection_state` | `src/selection/run_selection_engine_v2.py:61-179,369-433` |
| zone context | `SELECT` from `asset`; `SELECT` from `obs_market_candle` | `src/zone/repository.py:26-101` |
| zone context | `INSERT ... ON DUPLICATE KEY UPDATE` `fib_observation_v2`; `INSERT ... ON DUPLICATE KEY UPDATE` `zone_observation_v2` (both require `SELECT` on the target table) | `src/zone/repository.py:107-278` |
| zone context | `DELETE` then `UPSERT` `execution_zone_context` | `src/zone/repository.py:291-401` |
| setup filter | `SELECT` from `selection_state`/`asset`/`obs_market_candle` | `src/trade_setup_filter/repository.py:30-141` |
| setup filter metadata | `SELECT` from `information_schema.tables` | `src/trade_setup_filter/observation_repository.py:29-48` |
| setup filter observation | `UPSERT` `trade_setup_filter_observation` | `src/trade_setup_filter/observation_repository.py:82-151` |
| policy preview | two `SELECT` statements from `trade_setup_filter_observation`; `UPSERT` `trade_setup_policy_preview_observation` | `src/research/run_trade_setup_filter_policy_preview_v1.py:170-244,457-550` |
| paper advice A+ | `SELECT` from `aplus_table1_report`; `SELECT` from `aplus_table1_row` | `src/advice/run_paper_advice_policy_v1.py:47-97` |
| paper advice inputs | `SELECT` from `selection_state`, filter/policy observations, `execution_zone_context`, `asset`, and `vw_paper_advice_execution_zone_context_v1` | `src/advice/run_paper_advice_policy_v1.py:167-286` |
| paper advice observation | `INSERT ... ON DUPLICATE KEY UPDATE` `paper_advice_observation` (requires `SELECT` on the target table) | `src/advice/run_paper_advice_policy_v1.py:391-452` |
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
| `fib_observation_v2` | yes | yes | yes | no | zone upsert; `SELECT` required for `INSERT ... ON DUPLICATE KEY UPDATE` |
| `market_price_snapshot` | yes | no | no | no | freshness read |
| `native_short_map_generation_event_v1` | yes | yes | no | no | Native SHORT ledger/snapshot |
| `native_short_map_level_status_v1` | yes | yes | no | yes | projection replacement/snapshot |
| `native_short_map_level_target_event_coverage_v1` | yes | no | no | no | terminal-transition coverage read only; establishment (`INSERT`) not reachable from this identity's entrypoint |
| `native_short_map_level_target_event_v1` | yes | yes | no | no | terminal-transition target-event append; append-only, never `UPDATE`/`DELETE` |
| `native_short_map_lifecycle_event_v1` | yes | yes | no | no | Native SHORT ledger/snapshot |
| `native_short_map_scope_v1` | yes | yes | yes | no | scope selection and row lock; AUTO_ONBOARD_SCOPE `PROMOTE_NEW` insert / `PROMOTE_REACTIVATE` update; `DELETE` never issued (`REMOVE_SCOPE` soft-delete via `UPDATE` is not reachable from this chain) |
| `native_short_map_v1` | yes | yes | no | no | map materialization/snapshot |
| `native_short_materializer_run_v1` | yes | yes | yes | no | run insert/terminalize; `SELECT` required for compare-and-set `UPDATE ... WHERE run_id` |
| `native_short_scope_admin_operation_v1` | yes | yes | no | no | AUTO_ONBOARD_SCOPES idempotency ledger read (unconditional); ledger row insert on genuine onboarding only |
| `native_short_scope_cadence_config_v1` | yes | yes | no | no | cadence fact and row lock; AUTO_ONBOARD_SCOPE `PROMOTE_NEW`/`PROMOTE_REACTIVATE` insert; `UPDATE` (`_bind_legacy_cadence`/`_deactivate_cadence`) only reachable via `ADOPT_LEGACY_SCOPE`/`REMOVE_SCOPE`, not from this chain |
| `native_short_scope_observation_v1` | yes | yes | no | no | observation fact/append |
| `native_short_scope_status_v1` | yes | yes | yes | no | projection upsert/read |
| `native_short_scope_support_event_v1` | yes | yes | no | no | support fact read; AUTO_ONBOARD_SCOPE `PROMOTE_NEW`/`PROMOTE_REACTIVATE` append; append-only, never `UPDATE`/`DELETE` |
| `obs_market_candle` | yes | no | no | no | freshness/features/Native SHORT/zone/filter reads |
| `paper_advice_observation` | yes | yes | yes | no | paper-advice upsert; `SELECT` required for `INSERT ... ON DUPLICATE KEY UPDATE` |
| `ranking_state` | yes | yes | yes | no | ranking upsert; `SELECT` required for `INSERT ... ON DUPLICATE KEY UPDATE` |
| `selection_state` | yes | yes | yes | no | selection upsert; filter/advice reads |
| `signal_engine_state` | yes | yes | yes | no | signal upsert; advice/ranking/selection reads |
| `strategy_runtime_component` | no | yes | no | no | runtime metadata append |
| `strategy_runtime_snapshot` | no | yes | no | no | runtime metadata append |
| `trade_setup_filter_observation` | yes | yes | yes | no | filter upsert; policy/advice reads |
| `trade_setup_policy_preview_observation` | yes | yes | yes | no | policy upsert; advice read |
| `venue_market` | yes | no | no | no | public tick precision read |
| `vw_paper_advice_execution_zone_context_v1` | yes | no | no | no | paper-advice zone view read |
| `zone_observation_v2` | yes | yes | yes | no | zone upsert; `SELECT` required for `INSERT ... ON DUPLICATE KEY UPDATE` |

The quality snapshot no longer reads `v_asset_interval_quality_v3`; it reads only
exact-key bounded candle windows from `asset` and `obs_market_candle`. The canonical
authority contract and DBA artifact therefore no longer require that view grant.
Any obsolete grant already present on a deployed runtime identity must be revoked only
through a separately authorized production privilege change; this source change does
not mutate deployed grants.

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

## Safety Posture: Current Deployment Envelope

This contract provides bounded safety for the current Synth v2 deployment.

Current assumptions:

- `synth-chain-4h.service` is the only canonical caller using the
  `synth_chain_4h` database binding profile.
- The service unit and its non-secret environment metadata are maintained from
  this repository by the operator.
- The configured database endpoint, port, and password-file path are trusted
  deployment metadata, not untrusted user input.
- The runtime must use the exact dedicated identity
  `synth_chain_4h_writer` and database `synth`.
- Missing or invalid dedicated credentials must fail closed.
- Falling back to generic `DB_*`, `MYSQL_*`, or the broad `synth` identity is
  forbidden.
- The grant preflight must prove the exact least-privilege database authority
  before the chain runs.

The goal is not to make the shared database binding universally safe against
every possible caller, hostile environment mutation, arbitrary unit rewrite,
or future multi-service use.

The accepted safety claim is:

```text
SAFE_WITHIN_CURRENT_DEPLOYMENT_ENVELOPE
```

It must not be described as:

- universally hardened;
- tamper-proof;
- multi-tenant safe;
- safe for arbitrary external callers;
- safe for configurable database endpoints supplied by untrusted sources.

Exact enforcement of the canonical host, port, and password-file path inside
the shared binding loader is deferred hardening. It is not required for the
current single-caller deployment envelope.

This hardening becomes mandatory before any of the following changes:

- another service or caller uses the binding profile;
- database endpoints become configurable outside the canonical service unit;
- secret paths become configurable;
- multiple hosts, accounts, tenants, or runtime owners are supported;
- environment metadata can originate from an untrusted or user-controlled
  source;
- the binding module becomes a general-purpose runtime interface.

```text
current_safety_status=SAFE_WITHIN_CURRENT_DEPLOYMENT_ENVELOPE
universal_hardening=NOT_CLAIMED
single_canonical_caller=true
trusted_deployment_metadata=true
generic_db_fallback=FORBIDDEN
future_multi_caller_hardening=DEFERRED_TRIGGERED_TODO
```

The bounded claim is that the binding is demonstrably safe for the current
architecture, caller, and operator-controlled deployment boundary. Expanding
that boundary reopens the deferred hardening TODO.

## Target-Event Coverage Gap (corrected 2026-08-02)

Confirmed production failure on gurkdb, 2026-08-02, after the ETH and XRP
scope promotions were committed:

```text
MariaDB error 1142: SELECT command denied to user
'synth_chain_4h_writer'@'192.168.1.221' for table
synth.native_short_map_level_target_event_coverage_v1
```

Root cause: the `native_short_map_level_target_event_v1` /
`native_short_map_level_target_event_coverage_v1` migration
(`db/migrations/20260731_native_short_map_level_target_event_v1.sql`) and its
terminal-transition wiring into
`native_short_scope_status_materializer_v1._append_terminal_target_events`
(commit `d03adaad`) were added after the last review of
`src/operations/synth_chain_4h_db_authority_v1.py`
(commit `188dfac9`, 2026-07-30), so neither new table was ever added to the
required-object manifest, the DBA grant artifact, or this contract's call
graph and privilege matrix.

`_append_terminal_target_events` runs unconditionally, in the same
transaction, on every genuine `COMPLETED` lifecycle transition -- it is not
behind a feature flag or CLI opt-in. It always issues one `SELECT` against
`native_short_map_level_target_event_coverage_v1` first
(`fetch_target_event_coverage_for_map`), regardless of anything else. This
call did not exist as a reachable path for any scope until a scope's map
actually reached a `COMPLETED` transition in production, which is why the
gap was invisible until the ETH/XRP rollout produced one.

Correction, this change:

```text
native_short_map_level_target_event_coverage_v1.SELECT   = granted
native_short_map_level_target_event_coverage_v1.INSERT   = not granted (not reachable from this entrypoint; see below)
native_short_map_level_target_event_v1.SELECT            = granted
native_short_map_level_target_event_v1.INSERT            = granted
native_short_map_level_target_event_current_state_v1     = not granted (no runtime reader exists)
required_objects: 35 -> 37
```

Why coverage-table `INSERT` is deliberately not granted: establishment
(`establish_or_fetch_target_event_coverage_for_map`'s `INSERT` branch) only
runs when `append_native_short_map_level_target_events_for_map` receives a
non-`None` `requested_watermark_utc`. Tracing every caller reachable from
`scripts/run_chain_4h.sh` --
`run_native_short_scope_status_chain_v1.py` has no
`--target-event-coverage-watermark-utc` (or equivalent) CLI flag, and its one
call into `run_native_short_scope_status_materializer` does not pass
`target_event_coverage_watermark_utc`, so it is always `None` in this
identity's committed production wiring. If a coverage row already exists
(established by some other identity, e.g. the standalone
`run_native_short_map_level_status_materializer_v1` runner -- not wired to
any service/timer today, and not bound to this database identity), this
chain identity still only ever *reads* that row and appends further target
events; it never establishes one itself. If the automated chain's entrypoint
is ever changed to supply a real watermark, `INSERT` on the coverage table
must be added to the manifest, the DBA artifact, and this contract in that
same change -- it is not implicitly covered by this correction.

Why the reporting view `native_short_map_level_target_event_current_state_v1`
(defined by the same migration) is not granted: it has no reader anywhere in
`src/` today. Granting it now would be exactly the kind of blind, ahead-of-need
privilege this contract exists to avoid; add it, reviewed, in the change that
introduces its first reader.

This correction does not rewrite the "Complete Runtime Call Graph", "Executed
SQL Inventory", or "Exact Object-Level Privilege Matrix" sections above for
any pre-existing object -- it only adds the two new rows/entries and one new
call-graph branch. No prior acceptance observation elsewhere (Public Price
Snapshot, Public Candle Freshness, the SOL/ETH/XRP promotion approvals, or the
gurkDB `native_short_4h_chain` ownership preflight) is altered by this
section.

### Why the schema itself was never applied on gurkdb

The grant gap above is one symptom of a second, more basic gap: as of
2026-08-02, `native_short_map_level_target_event_coverage_v1` and
`native_short_map_level_target_event_v1` do not exist at all in the
production `synth` database on gurkdb (confirmed by the read-only
`synth-native-short-readiness-check` schema-existence check -- see
`docs/ops/native_short_production_promotion_wrapper_v1.md`). This is not a
defect in the migration file. This repository has no automatic migration
runner: every `db/migrations/*.sql` file is applied manually, one file at a
time, by an operator (see `docs/ops/native_short_scope_status_schema_deployment_20260708.md`
for the established precedent and its own evidence trail). The migration
that creates these two tables plus the `native_short_map_level_target_event_current_state_v1`
view --

```text
db/migrations/20260731_native_short_map_level_target_event_v1.sql
```

-- was merged into `main`, but its manual apply step on gurkdb was never
performed successfully. The first production apply attempt, 2026-08-03,
failed before creating any object (see "Overlong Constraint Identifier"
below) with a real schema-authoring defect in the migration file itself,
which has since been corrected in this repository. Until that correction is
re-applied on gurkdb, the schema gap remains open, purely operational (a
merged migration whose manual apply step has still not completed), on top of
the now-fixed authoring defect.

### Overlong Constraint Identifier (corrected 2026-08-03)

Confirmed production apply failure on gurkdb, 2026-08-03, on the first
attempt to run the recovery procedure below:

```text
ERROR 1059 (42000): Identifier name
'chk_native_short_map_level_target_event_v1_effective_matches_causal'
is too long
```

Root cause: two explicitly named `CHECK` constraints in
`db/migrations/20260731_native_short_map_level_target_event_v1.sql` exceeded
MariaDB's 64-character identifier limit --
`chk_native_short_map_level_target_event_v1_effective_matches_causal` (67
chars) and `chk_native_short_map_level_target_event_coverage_v1_cutoff_bounds`
(65 chars). This was a genuine schema-authoring defect, not merely an unapplied
migration; the prior claim in this document that "the file itself needs no
correction" was wrong and has been corrected above.

MariaDB reported the full intended `CREATE TABLE` statement in its error text
before rejecting the identifier, but validates identifier length before
committing any DDL, so **no table, constraint, index, or view was created** by
the failed attempt -- confirmed by the read-only
`synth-native-short-readiness-check` schema-existence check, unchanged, still
reporting both tables absent after the failed apply. The migration remains
`CREATE TABLE IF NOT EXISTS` / `CREATE OR REPLACE VIEW` throughout, so it stays
idempotent and safe to re-run in full from either starting state (nothing
created, or a future partial state), including after this fix.

Fix, this change: the two overlong constraint names were shortened, preserving
their exact `CHECK` semantics, to `chk_native_short_map_level_target_event_v1_eff_eq_causal`
(56 chars) and `chk_native_short_map_level_target_event_coverage_v1_cutoff_bnd`
(62 chars). No table, column, index, or other constraint changed. A focused
regression test (`tests/test_migration_identifier_length_v1.py`) now parses
every `db/migrations/*.sql` file for explicitly named identifiers and fails if
any exceeds 64 characters.

**No grants, readiness check, or service start followed the failed apply.**
Steps B, C, and D of the recovery procedure below were not reached on
2026-08-03 and remain outstanding; step A must be re-run with the corrected
migration file before B-D can proceed. This repository change performs no
database mutation, grant, or service action.

### Missing-schema recovery procedure (exact commands, not executed by this change)

Run on gurkdb, in order, after this change merges. None of these four steps
is executed as part of this repository change.

**A. Apply only the missing schema objects** (idempotent; touches only the
three objects this one file defines, no unrelated migration):

```bash
mysql -h 192.168.1.221 -P 3306 -u <db_admin_user> -p synth \
    < db/migrations/20260731_native_short_map_level_target_event_v1.sql
```

**B. Apply the two minimum grants** (see "Operator Grant Procedure" below for
the exact statements, or re-run the complete idempotent
`db/dba/synth_chain_4h_writer_v1.sql` artifact, which now includes them):

```bash
mysql -h 192.168.1.221 -P 3306 -u <db_admin_user> -p synth <<'SQL'
GRANT SELECT
    ON `synth`.`native_short_map_level_target_event_coverage_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT
    ON `synth`.`native_short_map_level_target_event_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
SQL
```

**C. Run the readiness check** (read-only; must report `ready=true` --
warnings, if any, do not block):

```bash
sudo synth-native-short-readiness-check
```

**D. Start the chain once** (the canonical oneshot unit; this does not enable
or activate the timer, which remains a separate, larger production-cutover
decision unrelated to this schema/grant fix):

```bash
sudo systemctl start synth-chain-4h.service
```

## Native SHORT Scope Administration Ledger Gap (corrected 2026-09-04)

Confirmed production failure on gurkdb, preflight reported `required_objects=37`
`status=PASS`, then runtime failed in the `AUTO_ONBOARD_SCOPES` phase:

```text
MariaDB error 1142: SELECT command denied to user
'synth_chain_4h_writer'@'192.168.1.221' for table
synth.native_short_scope_admin_operation_v1
```

Root cause: `run_native_short_scope_status_chain_v1.py` calls
`native_short_auto_onboarding_v1.reconcile_ready_scopes` unconditionally
whenever no explicit `symbols` are supplied -- the scheduled production
entrypoint always omits `symbols`, so this is not a rare or opt-in path. That
function calls `run_audit` (which reads `PROMOTE_SCOPE` rows from
`native_short_scope_admin_operation_v1`) and, for every candidate market,
`execute_scope_administration` with `operation_type=AUTO_ONBOARD_SCOPE`.
`execute_scope_administration` unconditionally reads the same table twice
before making any decision (`read_existing_operation`, then the operations
projection inside `read_scope_state_snapshot`) -- this table is, per its own
module docstring, "the sole idempotency authority" for every scope
administration operation, write-capable or not. When this identity's grant
was never extended past the 37-object manifest reviewed for the earlier
target-event correction, the very first `SELECT` in this path failed closed.

This is a distinct table and a distinct call path from the "Target-Event
Coverage Gap" above (`native_short_map_level_target_event_coverage_v1`,
reached only from the terminal-transition hook inside the materializer
transaction); it was missed by that review because `AUTO_ONBOARD_SCOPES` is a
separate phase, ahead of the writer commit fence and materializer, that the
prior review's call-graph trace did not walk.

`INSERT` is also required, not merely `SELECT`: `execute_scope_administration`
commits exactly one immutable terminal ledger row
(`_insert_operation`) atomically with its mutations whenever a decision
actually `writes_ledger` -- which is exactly what happens the first time a
READY market is onboarded to `SUPPORTED`. This is the entire purpose of
`AUTO_ONBOARD_SCOPES`, not a hypothetical branch, so `INSERT` is granted
alongside `SELECT`. No code path ever issues `UPDATE` or `DELETE` against this
table (ledger rows are immutable once committed), so neither is granted.

Correction, this change:

```text
native_short_scope_admin_operation_v1.SELECT = granted
native_short_scope_admin_operation_v1.INSERT = granted
native_short_scope_admin_operation_v1.UPDATE = not granted (no code path issues UPDATE)
native_short_scope_admin_operation_v1.DELETE = not granted (no code path issues DELETE)
required_objects: 37 -> 38
```

This correction does not rewrite any pre-existing row/entry in the "Complete
Runtime Call Graph", "Executed SQL Inventory", or "Exact Object-Level
Privilege Matrix" sections above -- it only adds the one new call-graph
branch, three new SQL Inventory rows, and one new matrix row.

Apply only the one new grant (host-side, not executed by this change):

```sql
GRANT SELECT, INSERT
    ON `synth`.`native_short_scope_admin_operation_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
```

Equivalently, re-running the complete, idempotent
`db/dba/synth_chain_4h_writer_v1.sql` artifact (which now includes this grant
alongside the unchanged complete set) achieves the same end state.

## Native SHORT Map Scope Onboard Gap (corrected 2026-09-04, second gap)

Confirmed production failure on gurkdb, immediately after the ledger-gap
correction above was applied: preflight passed (`required_objects=38`,
`status=PASS`), then runtime failed one step further into the same
`AUTO_ONBOARD_SCOPES` phase:

```text
MariaDB error 1142: INSERT command denied to user
synth_chain_4h_writer@192.168.1.221 for synth.native_short_map_scope_v1
```

Root cause: this identity's grant for `native_short_map_scope_v1` was
`SELECT`-only, reviewed only against the read-only call sites (`SELECT` from
`run_native_short_scope_status_chain_v1.py`, the writer commit fence, and
`native_short_map_materializer_v1.py`). It was never re-reviewed against the
write-capable `execute_scope_administration` path that
`native_short_auto_onboarding_v1.reconcile_ready_scopes` calls with
`operation_type=AUTO_ONBOARD_SCOPE` for every READY canonical market.

`decide_administration` routes `AUTO_ONBOARD_SCOPE` only into
`_decide_promote` (never `_decide_adopt` or `_decide_remove`), which yields
exactly three outcomes, independently confirmed against `_apply_decision`:

- `classify_scope_state == NO_SCOPE` (new READY scope, no prior row): action
  `PROMOTE_NEW` -> `_insert_scope_supported` -- `INSERT` into
  `native_short_map_scope_v1`. This is the branch that failed in production.
- `classify_scope_state == MANAGED_REMOVED` (re-support after a prior
  withdrawal/removal): action `PROMOTE_REACTIVATE` -> `_update_scope_promote`
  -- `UPDATE` of the existing `NOT_APPLICABLE` row back to `SUPPORTED`. Not yet
  observed in production, but independently reachable the first time a
  previously-withdrawn scope becomes READY again; granting only `INSERT` would
  leave this branch to fail closed later.
- `classify_scope_state == MANAGED_SUPPORTED` (already-supported/idempotent
  path): action `NOOP`, result `SCOPE_ALREADY_SUPPORTED` -- no mutation of
  `native_short_map_scope_v1` at all; covered by the existing `SELECT`.

`DELETE` is not required: no action reachable from `AUTO_ONBOARD_SCOPE` issues
a SQL `DELETE` against this table. `REMOVE_SCOPE`'s `_update_scope_remove` is
itself an `UPDATE` (soft-delete to `NOT_APPLICABLE`, not a row delete), and it
is only reachable via the `REMOVE_SCOPE` operation type, which
`reconcile_ready_scopes` never requests.

Correction, this change:

```text
native_short_map_scope_v1.SELECT = granted (unchanged)
native_short_map_scope_v1.INSERT = granted (new)
native_short_map_scope_v1.UPDATE = granted (new)
native_short_map_scope_v1.DELETE = not granted (no code path issues DELETE)
required_objects: 38 (unchanged -- existing object, privileges widened only)
```

This correction does not rewrite any pre-existing row/entry above except the
`native_short_map_scope_v1` row in "Exact Object-Level Privilege Matrix"; it
adds two new "Executed SQL Inventory" rows for the `PROMOTE_NEW`/
`PROMOTE_REACTIVATE` branches.

Apply only the one changed grant (host-side, not executed by this change):

```sql
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`native_short_map_scope_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
```

Equivalently, re-running the complete, idempotent
`db/dba/synth_chain_4h_writer_v1.sql` artifact (which now includes this
widened grant alongside the unchanged complete set) achieves the same end
state.

## Native SHORT Cadence/Support-Event Onboard Gap (audited proactively 2026-09-04, third gap)

Audited before deployment, not yet observed in production, to close out the
complete `AUTO_ONBOARD_SCOPES` write-set in one pass rather than discovering
the remaining gaps one MariaDB error 1142 at a time. The same
`_apply_decision` branches corrected above (`PROMOTE_NEW`, `PROMOTE_REACTIVATE`)
also call two more mutation helpers that were never re-reviewed against this
identity's grant:

- `_insert_active_cadence` -- `INSERT` into `native_short_scope_cadence_config_v1`
  (one new active cadence row per onboarding/re-support). Called by both
  `PROMOTE_NEW` and `PROMOTE_REACTIVATE`.
- `_insert_support_event` -- `INSERT` into `native_short_scope_support_event_v1`
  (one immutable support-event row per onboarding/re-support). Called by both
  `PROMOTE_NEW` and `PROMOTE_REACTIVATE`.

Both tables already carry `SELECT` for this identity (`read_scope_state_snapshot`
reads both unconditionally, and the writer commit fence separately locks the
cadence table), so the audit is `INSERT`-only for both. Independently checked
for `UPDATE`/`DELETE` reachability from this chain:

- `native_short_scope_cadence_config_v1` has two `UPDATE` sites,
  `_bind_legacy_cadence` and `_deactivate_cadence`. Both are called only from
  the `ADOPT` and `REMOVE` actions in `_apply_decision`, which
  `decide_administration` reaches only for `ADOPT_LEGACY_SCOPE` and
  `REMOVE_SCOPE` respectively -- `decide_administration` routes
  `AUTO_ONBOARD_SCOPE` exclusively to `_decide_promote`, so neither `UPDATE`
  site is reachable from this chain. Not granted.
- `native_short_scope_support_event_v1` has no `UPDATE` or `DELETE` statement
  anywhere in the module; it is append-only by design. Not granted.

A full re-audit of every `cur.execute` call reachable from
`reconcile_ready_scopes` -- across
`native_short_auto_onboarding_v1.py`, `native_short_multi_asset_audit_v1.py`,
`native_short_promotion_bootstrap_evidence_v1.py`, and
`native_short_scope_administration_transaction_v1.py` -- confirms the
complete write-set touched by `AUTO_ONBOARD_SCOPE` is exactly four tables:
`native_short_map_scope_v1`, `native_short_scope_cadence_config_v1`,
`native_short_scope_support_event_v1`, and
`native_short_scope_admin_operation_v1` (corrected in the first gap above).
`_revalidate_post_state` (run before every commit) and `run_audit` (the
readiness scan) are confirmed read-only. No fifth table requires a write
privilege not already represented in the authority manifest.

Correction, this change:

```text
native_short_scope_cadence_config_v1.SELECT = granted (unchanged)
native_short_scope_cadence_config_v1.INSERT = granted (new)
native_short_scope_cadence_config_v1.UPDATE = not granted (only ADOPT_LEGACY_SCOPE/REMOVE_SCOPE reach it)
native_short_scope_cadence_config_v1.DELETE = not granted (no code path issues DELETE)
native_short_scope_support_event_v1.SELECT = granted (unchanged)
native_short_scope_support_event_v1.INSERT = granted (new)
native_short_scope_support_event_v1.UPDATE = not granted (append-only, no code path issues UPDATE)
native_short_scope_support_event_v1.DELETE = not granted (append-only, no code path issues DELETE)
required_objects: 38 (unchanged -- both are existing objects, privileges widened only)
```

Apply only the two changed grants (host-side, not executed by this change):

```sql
GRANT SELECT, INSERT
    ON `synth`.`native_short_scope_cadence_config_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT
    ON `synth`.`native_short_scope_support_event_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
```

Equivalently, re-running the complete, idempotent
`db/dba/synth_chain_4h_writer_v1.sql` artifact (which now includes these
widened grants alongside the unchanged complete set) achieves the same end
state.

## Operator Grant Procedure (host-side, not executed by this change)

This repository change performs no database mutation, credential change, or
grant execution. After merge, on gurkdb, with a MariaDB session already
holding `@synth_chain_4h_writer_password` set from an approved secret
channel (exactly the existing procedure for `db/dba/synth_chain_4h_writer_v1.sql`),
apply only the changed/new grants from the three gap corrections above:

```sql
GRANT SELECT
    ON `synth`.`native_short_map_level_target_event_coverage_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT
    ON `synth`.`native_short_map_level_target_event_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT, UPDATE
    ON `synth`.`native_short_map_scope_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT
    ON `synth`.`native_short_scope_cadence_config_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
GRANT SELECT, INSERT
    ON `synth`.`native_short_scope_support_event_v1`
    TO 'synth_chain_4h_writer'@'192.168.1.%';
```

Equivalently, re-running the complete, idempotent
`db/dba/synth_chain_4h_writer_v1.sql` artifact (which now includes these
grants alongside the unchanged complete set) achieves the same end state; it
resets and re-grants only the dedicated `synth_chain_4h_writer` identity and
does not touch the existing broad `synth` identity or any other user.

Verify with the existing read-only preflight, unchanged:

```bash
python -m src.operations.run_synth_chain_4h_db_grant_preflight_v1
```

It must report `required_objects=38` and `status=PASS`. Neither the grant nor
any production restart is executed by this repository change; both remain
separate, explicit host-side operator actions.

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
