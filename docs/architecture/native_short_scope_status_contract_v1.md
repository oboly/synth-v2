# Native SHORT Scope Status Persistence Contract V1

## Status

Contract freeze for PR A0. This document is documentation-only and defines the
MariaDB persistence and projection contract required before PR A1 implementation
starts.

## Ownership And Boundaries

This contract belongs to the market-data/native SHORT runtime lane.

Required boundaries:

- Market-only.
- Account-agnostic.
- Public persisted candle inputs only.
- No broker or private account calls.
- No broker writes.
- No decision gate, execution planner, executor, or order handling layers.
- No scheduler, service, timer, wrapper, or production runtime deployment.
- No dashboard or UI work.

Safety markers for implementation work derived from this contract:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

## Existing Authoritative Ledgers

The status projection is derived from existing native SHORT and candle facts.
Authoritative sources are:

- `native_short_map_scope_v1`: supported scope inventory and canonical scope key.
- `native_short_map_v1`: immutable map geometry and publication facts.
- `native_short_map_generation_event_v1`: publication/rejection/failure provenance.
- `native_short_map_lifecycle_event_v1`: lifecycle transitions.
- persisted market candles for the native SHORT primary and supporting intervals.
- the new `native_short_materializer_run_v1` table.
- the new `native_short_scope_observation_v1` table.
- the new cadence/grace configuration owner defined below.

Operational reporting must read `native_short_scope_status_v1`. Reporting must
not independently infer current freshness from immutable map timestamps.

## Canonical Scope Key

Every new entity uses the existing full native SHORT scope key. Symbol-only
identity is forbidden.

Canonical key fields:

```text
venue
symbol
quote_currency
fib_trading_horizon
primary_interval
supporting_interval
```

Recommended uniqueness for scope-owned tables is always based on all six fields,
not on `symbol` alone.

## Entity: native_short_materializer_run_v1

Purpose: append-only operational evidence for one bounded materializer run. A run
may cover one or more SUPPORTED scopes. It is not a strategy decision and not an
execution permission.

Mutability: append-only. A row is inserted at run start and may be updated once
at terminal completion to set terminal fields. After terminal completion it is
immutable.

Retention: retain at least 90 days of run records. Longer retention is preferred
while PR A is being validated. Cleanup must not remove rows still referenced by
retained observations.

Keys and indexes:

- Primary key: `run_id`.
- Unique key: `run_uuid`.
- Index: `(started_at_utc)`.
- Index: `(runner_name, runner_version, started_at_utc)`.
- Index: `(terminal_status, finished_at_utc)`.

Fields:

| Field | Type intent for MariaDB | Required | Writer | Meaning | Mutability |
|---|---|---:|---|---|---|
| `run_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | yes | MariaDB | Surrogate run identifier | immutable |
| `run_uuid` | `CHAR(36)` | yes | materializer runtime | Stable UUID for logs and observations | immutable |
| `runner_name` | `VARCHAR(96)` | yes | materializer runtime | Runner name, e.g. native SHORT materializer | immutable |
| `runner_version` | `VARCHAR(32)` | yes | materializer runtime | Runner implementation version | immutable |
| `contract_version` | `VARCHAR(32)` | yes | materializer runtime | Scope-status contract version used by this run | immutable |
| `trigger_type` | `VARCHAR(64)` | yes | materializer runtime | Manual, canary, runtime owner, or bounded operator trigger | immutable |
| `trigger_ref` | `VARCHAR(255)` | no | materializer runtime | Optional operator/job reference | immutable |
| `host_name` | `VARCHAR(128)` | no | materializer runtime | Host that executed the run | immutable |
| `process_id` | `INT UNSIGNED` | no | materializer runtime | OS process id for diagnostics | immutable |
| `started_at_utc` | `DATETIME(6)` | yes | materializer runtime | UTC run start timestamp | immutable |
| `finished_at_utc` | `DATETIME(6)` | no | materializer runtime | UTC terminal timestamp | set once |
| `terminal_status` | `VARCHAR(32)` | no | materializer runtime | `FINISHED`, `FAILED`, or `INTERRUPTED` | set once |
| `requested_scope_count` | `INT UNSIGNED` | yes | materializer runtime | Number of scopes requested for evaluation | immutable |
| `observed_scope_count` | `INT UNSIGNED` | no | materializer runtime | Number of observation rows written | set once |
| `published_map_count` | `INT UNSIGNED` | no | materializer runtime | Number of new immutable maps published | set once |
| `lifecycle_event_count` | `INT UNSIGNED` | no | materializer runtime | Number of lifecycle transition rows appended | set once |
| `failed_scope_count` | `INT UNSIGNED` | no | materializer runtime | Number of scope observations with failed evaluation | set once |
| `failure_reason_code` | `VARCHAR(96)` | no | materializer runtime | Run-level failure code when terminal status is failed | set once |
| `failure_detail` | `TEXT` | no | materializer runtime | Bounded non-secret diagnostic detail | set once |
| `created_at_utc` | `DATETIME(6)` | yes | materializer runtime | Row creation timestamp | immutable |
| `updated_at_utc` | `DATETIME(6)` | yes | materializer runtime | Last terminal update timestamp | set once after insert |

## Entity: native_short_scope_observation_v1

Purpose: append-only per-scope evaluation evidence. Each row records what the
materializer observed for one canonical scope at one evaluation time, including
source freshness, unchanged-geometry results, failures, and lifecycle transition
outputs.

Mutability: append-only. Rows are never updated after insertion.

Retention: retain at least 180 days. Retention must preserve enough evidence to
explain every retained `native_short_scope_status_v1` row and recent health
reports.

Keys and indexes:

- Primary key: `scope_observation_id`.
- Foreign key intent: `run_id` references `native_short_materializer_run_v1(run_id)`.
- Index: full canonical scope key plus `observed_at_utc`.
- Index: `(run_id)`.
- Index: `(map_id)`.
- Index: `(observation_status, observed_at_utc)`.
- Index: `(source_state, observed_at_utc)`.
- Optional idempotency unique key: `(run_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval)`.

Fields:

| Field | Type intent for MariaDB | Required | Writer | Meaning | Mutability |
|---|---|---:|---|---|---|
| `scope_observation_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | yes | MariaDB | Surrogate observation id | immutable |
| `run_id` | `BIGINT UNSIGNED` | yes | materializer runtime | Parent run id | immutable |
| `run_uuid` | `CHAR(36)` | yes | materializer runtime | Denormalized run UUID for diagnostics | immutable |
| `venue` | `VARCHAR(32)` | yes | materializer runtime | Canonical scope key | immutable |
| `symbol` | `VARCHAR(32)` | yes | materializer runtime | Canonical scope key | immutable |
| `quote_currency` | `VARCHAR(16)` | yes | materializer runtime | Canonical scope key | immutable |
| `fib_trading_horizon` | `VARCHAR(32)` | yes | materializer runtime | Canonical scope key; `SHORT` is tactical horizon | immutable |
| `primary_interval` | `VARCHAR(16)` | yes | materializer runtime | Canonical scope key | immutable |
| `supporting_interval` | `VARCHAR(16)` | yes | materializer runtime | Canonical scope key | immutable |
| `observed_at_utc` | `DATETIME(6)` | yes | materializer runtime | UTC timestamp of scope evaluation | immutable |
| `evaluation_due_at_utc` | `DATETIME(6)` | no | materializer runtime | Expected due time under cadence/grace contract | immutable |
| `cadence_contract_version` | `VARCHAR(32)` | yes | materializer runtime | Version of cadence/grace config used | immutable |
| `observation_status` | `VARCHAR(64)` | yes | materializer runtime | `EVALUATED`, `FAILED`, `SKIPPED_SCOPE_NOT_APPLICABLE`, or `SKIPPED_SOURCE_UNAVAILABLE` | immutable |
| `observation_reason_code` | `VARCHAR(96)` | no | materializer runtime | Stable reason for failure or skip | immutable |
| `observation_detail` | `TEXT` | no | materializer runtime | Bounded non-secret diagnostic detail | immutable |
| `source_state` | `VARCHAR(64)` | yes | materializer runtime | `SOURCE_CURRENT`, `SOURCE_STALE`, or `SOURCE_UNAVAILABLE` | immutable |
| `primary_latest_candle_ts_utc` | `DATETIME(6)` | no | materializer runtime | Latest persisted primary candle close timestamp used | immutable |
| `supporting_latest_candle_ts_utc` | `DATETIME(6)` | no | materializer runtime | Latest persisted supporting candle close timestamp used | immutable |
| `primary_source_age_seconds` | `INT UNSIGNED` | no | materializer runtime | Age of latest primary candle at observation time | immutable |
| `supporting_source_age_seconds` | `INT UNSIGNED` | no | materializer runtime | Age of latest supporting candle at observation time | immutable |
| `primary_source_freshness_limit_seconds` | `INT UNSIGNED` | yes | materializer runtime | Freshness bound used for primary interval | immutable |
| `supporting_source_freshness_limit_seconds` | `INT UNSIGNED` | yes | materializer runtime | Freshness bound used for supporting interval | immutable |
| `context_status` | `VARCHAR(96)` | no | materializer runtime | Native SHORT context status from context builder | immutable |
| `current_map_id_before` | `BIGINT UNSIGNED` | no | materializer runtime | Active map id before evaluation | immutable |
| `current_map_id_after` | `BIGINT UNSIGNED` | no | materializer runtime | Active/current map id after evaluation and transition handling | immutable |
| `published_map_id` | `BIGINT UNSIGNED` | no | materializer runtime | New map id when geometry was published | immutable |
| `generation_attempt_id` | `CHAR(36)` | no | materializer runtime | Generation attempt id when generation ledger was touched | immutable |
| `generation_event_id` | `BIGINT UNSIGNED` | no | materializer runtime | Terminal generation event id for this observation, if any | immutable |
| `lifecycle_event_id` | `BIGINT UNSIGNED` | no | materializer runtime | Lifecycle transition event id appended by this observation, if any | immutable |
| `lifecycle_state_before` | `VARCHAR(64)` | no | materializer runtime | Derived lifecycle state before observation | immutable |
| `lifecycle_state_after` | `VARCHAR(64)` | no | materializer runtime | Derived lifecycle state after observation | immutable |
| `geometry_action` | `VARCHAR(64)` | yes | materializer runtime | `PUBLISHED_NEW_MAP`, `UNCHANGED_GEOMETRY`, `REJECTED_CONTEXT`, or `NO_MAP_AVAILABLE` | immutable |
| `structure_hash` | `CHAR(64)` | no | materializer runtime | Map structure hash evaluated for idempotency | immutable |
| `source_primary_candle_count` | `INT UNSIGNED` | no | materializer runtime | Primary candles available to context builder | immutable |
| `source_support_candle_count` | `INT UNSIGNED` | no | materializer runtime | Supporting candles available to context builder | immutable |
| `created_at_utc` | `DATETIME(6)` | yes | materializer runtime | Row creation timestamp | immutable |

## Entity: native_short_scope_status_v1

Purpose: rebuildable current market projection with exactly one canonical row per
SUPPORTED scope. It is a display/reporting and health input, not a decision gate
and not execution intent.

Mutability: rebuildable projection. Rows may be deleted and rebuilt, or upserted
from authoritative sources, as long as the resulting contents are deterministic.
The table is not authoritative history.

Retention: current-row projection only. Historical status is reconstructed from
run, observation, map, generation, lifecycle, and candle facts.

Keys and indexes:

- Primary key: `scope_status_id`; canonical uniqueness remains the full scope key.
- Unique key: `(venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval)`.
- Index: `(scope_status_code)`.
- Index: `(actionability_state)`.
- Index: `(latest_observed_at_utc)`.
- Index: `(current_map_id)`.

Fields:

| Field | Type intent for MariaDB | Required | Writer | Meaning | Mutability |
|---|---|---:|---|---|---|
| `scope_status_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | yes | projection rebuild process | Surrogate projection id | rebuildable |
| `venue` | `VARCHAR(32)` | yes | projection rebuild process | Canonical scope key | rebuildable |
| `symbol` | `VARCHAR(32)` | yes | projection rebuild process | Canonical scope key | rebuildable |
| `quote_currency` | `VARCHAR(16)` | yes | projection rebuild process | Canonical scope key | rebuildable |
| `fib_trading_horizon` | `VARCHAR(32)` | yes | projection rebuild process | Canonical scope key; `SHORT` is tactical horizon | rebuildable |
| `primary_interval` | `VARCHAR(16)` | yes | projection rebuild process | Canonical scope key | rebuildable |
| `supporting_interval` | `VARCHAR(16)` | yes | projection rebuild process | Canonical scope key | rebuildable |
| `scope_support_state` | `VARCHAR(64)` | yes | projection rebuild process | Scope support state from scope table | rebuildable |
| `scope_status_code` | `VARCHAR(64)` | yes | projection rebuild process | One canonical status code under precedence below | rebuildable |
| `scope_status_reason_code` | `VARCHAR(96)` | no | projection rebuild process | Stable reason for current status | rebuildable |
| `map_lifecycle_state` | `VARCHAR(64)` | yes | projection rebuild process | Current map lifecycle state, independent from observation freshness | rebuildable |
| `observation_freshness_state` | `VARCHAR(64)` | yes | projection rebuild process | `OBSERVATION_CURRENT`, `OBSERVATION_OVERDUE`, or `NO_OBSERVATION` | rebuildable |
| `source_freshness_state` | `VARCHAR(64)` | yes | projection rebuild process | `SOURCE_CURRENT`, `SOURCE_STALE`, or `SOURCE_UNAVAILABLE` | rebuildable |
| `actionability_state` | `VARCHAR(64)` | yes | projection rebuild process | Human-safe market-only actionability classification | rebuildable |
| `current_map_id` | `BIGINT UNSIGNED` | no | projection rebuild process | Current active or latest terminal map id, if any | rebuildable |
| `current_map_cycle_id` | `VARCHAR(255)` | no | projection rebuild process | Map cycle id for the current map | rebuildable |
| `current_map_published_at_utc` | `DATETIME(6)` | no | projection rebuild process | Immutable map publication timestamp | rebuildable |
| `current_map_structure_hash` | `CHAR(64)` | no | projection rebuild process | Current map structure hash | rebuildable |
| `latest_generation_event_id` | `BIGINT UNSIGNED` | no | projection rebuild process | Latest authoritative generation event for scope | rebuildable |
| `latest_lifecycle_event_id` | `BIGINT UNSIGNED` | no | projection rebuild process | Latest lifecycle event for current map | rebuildable |
| `latest_observation_id` | `BIGINT UNSIGNED` | no | projection rebuild process | Latest scope observation used | rebuildable |
| `latest_run_id` | `BIGINT UNSIGNED` | no | projection rebuild process | Parent run for latest observation | rebuildable |
| `latest_observed_at_utc` | `DATETIME(6)` | no | projection rebuild process | Last scope observation timestamp | rebuildable |
| `next_expected_evaluation_at_utc` | `DATETIME(6)` | no | projection rebuild process | Next expected evaluation under cadence contract | rebuildable |
| `observation_overdue_after_utc` | `DATETIME(6)` | no | projection rebuild process | Time after which observation becomes overdue | rebuildable |
| `primary_latest_candle_ts_utc` | `DATETIME(6)` | no | projection rebuild process | Latest primary candle timestamp used for current source state | rebuildable |
| `supporting_latest_candle_ts_utc` | `DATETIME(6)` | no | projection rebuild process | Latest supporting candle timestamp used for current source state | rebuildable |
| `primary_source_freshness_limit_seconds` | `INT UNSIGNED` | yes | projection rebuild process | Active primary source freshness bound | rebuildable |
| `supporting_source_freshness_limit_seconds` | `INT UNSIGNED` | yes | projection rebuild process | Active supporting source freshness bound | rebuildable |
| `cadence_contract_version` | `VARCHAR(32)` | yes | projection rebuild process | Cadence/grace config version applied | rebuildable |
| `status_payload_json` | `JSON` | no | projection rebuild process | Bounded deterministic diagnostics for reporting | rebuildable |
| `rebuilt_at_utc` | `DATETIME(6)` | yes | projection rebuild process | Projection rebuild timestamp | rebuildable |

## Cadence And Grace Configuration Ownership

Cadence and grace must be persisted in a market-data configuration owner. They
must not be inferred only from systemd, timers, crontab, wrappers, or operator
memory.

The proposed persistence owner is `native_short_scope_cadence_config_v1`.
PR A1 migrations must either implement this table name exactly or update this
contract before merge with an equivalent explicit MariaDB owner.

Mutability: versioned configuration. New versions are inserted or activated with
explicit effective timestamps. Historical observations retain the
`cadence_contract_version` they used.

Recommended keys and indexes:

- Primary key: `cadence_config_id`.
- Unique key: full canonical scope key plus `cadence_contract_version`.
- Index: full canonical scope key plus `effective_from_utc`.
- Index: `(is_active)`.

Required configuration fields:

| Field | Type intent for MariaDB | Required | Writer | Meaning | Mutability |
|---|---|---:|---|---|---|
| `cadence_config_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | yes | migration/config owner | Surrogate config id | immutable |
| `venue` | `VARCHAR(32)` | yes | migration/config owner | Canonical scope key or wildcard only if explicitly supported | immutable per version |
| `symbol` | `VARCHAR(32)` | yes | migration/config owner | Canonical scope key or wildcard only if explicitly supported | immutable per version |
| `quote_currency` | `VARCHAR(16)` | yes | migration/config owner | Canonical scope key | immutable per version |
| `fib_trading_horizon` | `VARCHAR(32)` | yes | migration/config owner | Canonical scope key | immutable per version |
| `primary_interval` | `VARCHAR(16)` | yes | migration/config owner | Canonical scope key; native default `4h` | immutable per version |
| `supporting_interval` | `VARCHAR(16)` | yes | migration/config owner | Canonical scope key; native default `1h` | immutable per version |
| `cadence_contract_version` | `VARCHAR(32)` | yes | migration/config owner | Version label used by observations/status | immutable |
| `target_evaluation_interval` | `VARCHAR(16)` | yes | migration/config owner | Interval that drives expected evaluation; native default `1h` | immutable |
| `primary_source_freshness_limit_seconds` | `INT UNSIGNED` | yes | migration/config owner | Native default 12 hours | immutable per version |
| `supporting_source_freshness_limit_seconds` | `INT UNSIGNED` | yes | migration/config owner | Native default 3 hours | immutable per version |
| `evaluation_grace_seconds` | `INT UNSIGNED` | yes | migration/config owner | Explicit grace after expected persisted closed 1h candle | immutable per version |
| `recent_scope_grace_seconds` | `INT UNSIGNED` | yes | migration/config owner | Grace for newly supported scopes before overdue classification | immutable per version |
| `effective_from_utc` | `DATETIME(6)` | yes | migration/config owner | Version activation start | immutable |
| `effective_to_utc` | `DATETIME(6)` | no | migration/config owner | Version activation end | set once |
| `is_active` | `TINYINT(1)` | yes | migration/config owner | Active version marker if used | rebuildable/config-managed |
| `created_at_utc` | `DATETIME(6)` | yes | migration/config owner | Row creation timestamp | immutable |

Current native SHORT defaults:

```text
primary interval: 4h
primary source freshness: 12h
supporting interval: 1h
supporting source freshness: 3h
target evaluation: after each persisted closed 1h candle plus explicit grace
```

## Status Precedence

`native_short_scope_status_v1.scope_status_code` is a single canonical code. The
projection may expose separate lifecycle, observation freshness, source
freshness, and actionability fields, but the top-level code must be deterministic
when multiple conditions exist.

Precedence from highest to lowest:

1. `SCOPE_NOT_APPLICABLE`
2. `SOURCE_UNAVAILABLE`
3. `SOURCE_STALE`
4. `MAP_INVALIDATED`
5. `MAP_COMPLETED`
6. `SCOPE_RECENTLY_ADDED`
7. `OBSERVATION_OVERDUE`
8. `CURRENT_EVALUATION`

Meanings:

| Code | Mutually exclusive meaning |
|---|---|
| `SCOPE_NOT_APPLICABLE` | Scope is not currently `SUPPORTED` or cannot be evaluated under the native SHORT scope contract. No current map is actionable. |
| `SOURCE_UNAVAILABLE` | Required persisted candle source data is absent or insufficient to determine current source freshness. This is about market input availability, not runtime cadence. |
| `SOURCE_STALE` | Required candle source exists but latest primary or supporting candle violates its configured freshness bound. This is market-data staleness, even if the runtime ran on time. |
| `MAP_INVALIDATED` | Current map has a terminal invalidation lifecycle event. Lifecycle terminal state outranks overdue observation because the map is no longer active. |
| `MAP_COMPLETED` | Current map has a terminal completed lifecycle event. Lifecycle terminal state outranks overdue observation because the map already reached terminal success. |
| `SCOPE_RECENTLY_ADDED` | Scope is SUPPORTED but is still within configured recent-scope grace and lacks sufficient observation history. This prevents immediate false overdue alerts. |
| `OBSERVATION_OVERDUE` | Candle source is available/current enough, but the latest materializer observation is missing or older than the expected cadence plus grace. This is runtime observation staleness, not candle staleness. |
| `CURRENT_EVALUATION` | Scope is SUPPORTED, source is available/current, observation is within cadence/grace, and map lifecycle is non-terminal or no map exists yet. |

Lifecycle state versus observation/freshness state:

- `map_lifecycle_state` describes the current map only: active, invalidated,
  completed, expired, superseded, or no map.
- `observation_freshness_state` describes whether the materializer evaluated the
  scope within the cadence/grace contract.
- `source_freshness_state` describes persisted candle availability and age.
- These states are stored separately because a terminal map can be fresh, stale,
  or overdue, and a current observation can still report stale source data.

Actionability state:

- `ACTIONABLE_ACTIVE_MAP`: non-terminal current map, current source, current observation.
- `NO_ACTIONABLE_MAP`: no current map exists, but the scope is otherwise current.
- `TERMINAL_MAP`: current map is completed, invalidated, expired, or superseded.
- `BLOCKED_SOURCE`: source is stale or unavailable.
- `BLOCKED_OBSERVATION`: runtime observation is overdue.
- `BLOCKED_SCOPE`: scope is not applicable or recently added inside grace.

When multiple conditions exist, the canonical current row stores the highest
precedence `scope_status_code`, while the separate state fields preserve the
lower-precedence facts. Example: if source data is stale and the latest
observation is overdue, the canonical code is `SOURCE_STALE`, with
`observation_freshness_state=OBSERVATION_OVERDUE`.

Exact stale-versus-overdue distinction:

- `SOURCE_STALE` means the persisted 4h or 1h candle input is too old under the
  configured source freshness bound.
- `OBSERVATION_OVERDUE` means the materializer did not produce a recent enough
  scope observation under the configured evaluation cadence/grace while source
  data is available and not stale.

## Projection Rebuild Contract

Authoritative inputs:

- `native_short_map_scope_v1`
- cadence/grace configuration owner
- `native_short_materializer_run_v1`
- `native_short_scope_observation_v1`
- `native_short_map_v1`
- `native_short_map_generation_event_v1`
- `native_short_map_lifecycle_event_v1`
- persisted primary and supporting candles


Deterministic rebuild ordering for each canonical scope:

1. Load SUPPORTED scope rows from `native_short_map_scope_v1` using full key ordering.
2. Load active cadence/grace config by full key and effective timestamp.
3. Load latest scope observation by `(observed_at_utc, scope_observation_id)`.
4. Load candidate current map by immutable map facts and lifecycle terminal state.
5. Load latest generation event by `(generation_event_id)` for the scope.
6. Load latest lifecycle event by `(lifecycle_event_id)` for the chosen map.
7. Load latest primary and supporting candle timestamps.
8. Compute source freshness, observation freshness, lifecycle state, actionability, and top-level status by precedence.
9. Write exactly one projection row for the SUPPORTED scope.

Idempotency:

- Rebuilding the projection from unchanged authoritative inputs must produce the
  same canonical rows except `rebuilt_at_utc`.
- Rebuild logic must not insert generation events, lifecycle events, maps, or
  observations.
- Rebuild logic must not mutate immutable map timestamps.

Delete/rebuild versus upsert:

- Full delete-and-rebuild is acceptable for all SUPPORTED scopes inside one
  bounded transaction if readers never see an empty partial table.
- Per-scope upsert is acceptable if it uses the full canonical scope key and is
  deterministic.
- Mixed partial rebuilds must identify the scope set explicitly and must not
  leave stale rows for scopes that are no longer SUPPORTED.

Required behavior:

- One canonical row exists per SUPPORTED scope.
- If no map exists, set `map_lifecycle_state=NO_MAP` and use `CURRENT_EVALUATION`
  only when source and observation are current; otherwise apply source/observation
  precedence.
- If latest observation failed, preserve the failure reason in
  `scope_status_reason_code` and status payload. Classify by source state first,
  then overdue/current observation rules, unless the failure proves
  `SOURCE_UNAVAILABLE`.
- If a map is terminal, set `MAP_INVALIDATED` or `MAP_COMPLETED` when applicable;
  expired/superseded terminal maps use `map_lifecycle_state` plus
  `actionability_state=TERMINAL_MAP` and the highest matching status code defined
  above.
- A newly added SUPPORTED scope with insufficient observation evidence is
  `SCOPE_RECENTLY_ADDED` until recent-scope grace expires. After grace, if source
  exists and is current but no observation exists, it becomes `OBSERVATION_OVERDUE`.

## Lifecycle Transition Ownership

Lifecycle transition detection belongs to PR A2 materializer integration, not to
health reporting and not to dashboards.

Rules:

- Lifecycle events append only on real transitions.
- Unchanged geometry must not create duplicate maps.
- Unchanged geometry may still produce a lifecycle transition when current market
  evidence reaches completion, invalidation, expiry, or supersession conditions.
- No generation-event heartbeat is allowed for routine unchanged evaluations.
- Immutable map timestamps must never be mutated to simulate current freshness.
- Projection rebuild may read lifecycle events but must not create them.

## Migration And Rollout Plan

### PR A1 — Migrations And Types Only

- Add MariaDB migrations only for the persistence contract.
- Add model and validation types for run, observation, cadence, and status rows.
- No materializer runner integration.
- No lifecycle transition detection.
- No health-report switch.
- No systemd, timer, wrapper, or runtime deployment.

### PR A2 — Materializer Integration And Projection

- Record materializer run rows.
- Record per-scope observation rows.
- Implement projection rebuild logic for `native_short_scope_status_v1`.
- Implement lifecycle transition detection that appends only real transition events.
- No systemd, timer, wrapper, or runtime deployment.
- No dashboard/UI work.

### PR A3 — Health Report Consumption

- Change native SHORT health reporting to consume `native_short_scope_status_v1`.
- Stop inferring runtime freshness from immutable map timestamps.
- No UI/dashboard work.
- No systemd, timer, wrapper, or runtime deployment.

### PR B — Runtime Owner Deployment

- Runtime owner deployment only after PR #54 / P0-A is merged and accepted.
- Add wrapper/service/timer only in PR B, not in PR A0/A1/A2/A3.
- Preserve bounded logging and disk/log health containment accepted by P0-A.

## Acceptance Criteria

PR A1 acceptance:

- MariaDB migration defines run, observation, projection, and cadence/grace
  persistence using the full canonical scope key.
- Migration tests or SQL inspections prove required keys and indexes exist.
- Model/validation tests reject symbol-only identity.
- No runner code imports or writes the new tables.
- No health report reads the new projection.
- No scheduler, service, timer, wrapper, broker, execution, or UI files change.

PR A2 acceptance:

- Tests prove each materializer run writes one run record and deterministic
  per-scope observation records.
- Tests prove unchanged geometry does not publish duplicate maps and does not emit
  generation-event heartbeat rows.
- Tests prove unchanged geometry can still append exactly one real lifecycle
  transition event.
- Tests prove projection rebuild is idempotent from authoritative inputs.
- Tests cover no-map, failed-observation, terminal-map, source-stale,
  source-unavailable, observation-overdue, and recently-added-scope cases.
- No systemd, timer, wrapper, broker, execution, or UI files change.

PR A3 acceptance:

- Health report reads `native_short_scope_status_v1` for freshness/status.
- Tests prove immutable map `published_at_utc` is not used as runtime freshness.
- Tests prove stale source data and overdue observation are reported distinctly.
- No UI/dashboard work is included.
- No systemd, timer, wrapper, broker, or execution files change.

PR B acceptance:

- PR #54 / P0-A is merged and accepted before deployment work begins.
- One runtime owner wrapper and one service/timer pair are introduced.
- Host singleton lock and existing per-scope DB lock are preserved.
- Logs are bounded and operationally readable.
- Rollback disables/removes runtime owner only and never mutates ledger history.
- Broker/private calls, broker writes, decision gate, planner, executor, and order
  submission remain absent.

## Explicit Non-Goals

- No runtime deployment.
- No systemd changes.
- No timer changes.
- No wrapper creation.
- No broker or private account calls.
- No broker writes.
- No decision_gate changes.
- No execution_planner changes.
- No planner/executor changes.
- No Profit Plan consumption yet.
- No replay or backtest work.
- No map geometry redesign.
- No automatic scope seeding.
- No dashboard/UI work.
- No `SHORT` rename; `SHORT` remains a tactical horizon, not bearish direction.
