# Native SHORT Scope Status Persistence Contract V1

## Status

Contract freeze for PR A0. This document is documentation-only and defines the
MariaDB persistence and projection contract required before PR A1 implementation
starts.

### Amendment 1 — Cadence-Configuration-Unavailable State

PR A2 Phase 0 review found that a SUPPORTED scope can have zero eligible
`native_short_scope_cadence_config_v1` rows at a given `as_of_utc` (this is the
actual current state immediately after the PR A1 migration, which creates the
table but backfills no rows). The frozen v1 text required "fail closed with a
deterministic configuration reason" but left `cadence_contract_version`,
freshness-limit fields, `source_state`, and `geometry_action` as unconditionally
required (`NOT NULL`) on both `native_short_scope_observation_v1` and
`native_short_scope_status_v1`, with no reason code, observation status, top-level
status code, or actionability state defined for this case. That combination made
the required fail-closed behavior unrepresentable without inventing sentinel
values or misclassifying a configuration defect as a source-availability
problem.

This amendment defines the `NO_ELIGIBLE_CADENCE_CONFIG` reason code, the
`SKIPPED_CONFIGURATION_UNAVAILABLE` observation status, the
`CONFIGURATION_UNAVAILABLE` top-level status code, the `BLOCKED_CONFIGURATION`
actionability state, and the `OBSERVATION_CONFIGURATION_UNAVAILABLE` observation
freshness state, and reconciles every affected section below. It also inserts a
new PR A1b (narrow schema/type change) between PR A1 and PR A2 in the rollout
plan; PR A2 materializer/projection implementation must not begin until PR A1b
merges. This amendment is documentation-only: it defines no migration and no
runtime code.

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

- `native_short_map_scope_v1`: mutable current scope registry for ordinary live operation.
- `native_short_scope_support_event_v1`: append-only support-state provenance for cutoff/historical reconstruction.
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
outputs. A row is also written when evaluation could not start because no
cadence configuration was eligible; see Conditional Nullability below.

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
| `evaluation_due_at_utc` | `DATETIME(6)` | no | materializer runtime | Expected due time under cadence/grace contract; MUST be NULL when `observation_status=SKIPPED_CONFIGURATION_UNAVAILABLE` | immutable |
| `cadence_contract_version` | `VARCHAR(32)` | yes* | materializer runtime | Version of cadence/grace config used; MUST be NULL when `observation_status=SKIPPED_CONFIGURATION_UNAVAILABLE` (see Conditional Nullability) | immutable |
| `observation_status` | `VARCHAR(64)` | yes | materializer runtime | `EVALUATED`, `FAILED`, `SKIPPED_SOURCE_UNAVAILABLE`, or `SKIPPED_CONFIGURATION_UNAVAILABLE` | immutable |
| `observation_reason_code` | `VARCHAR(96)` | no | materializer runtime | Stable reason for failure or skip; MUST equal `NO_ELIGIBLE_CADENCE_CONFIG` when `observation_status=SKIPPED_CONFIGURATION_UNAVAILABLE` | immutable |
| `observation_detail` | `TEXT` | no | materializer runtime | Bounded non-secret diagnostic detail | immutable |
| `source_state` | `VARCHAR(64)` | yes* | materializer runtime | `SOURCE_CURRENT`, `SOURCE_STALE`, or `SOURCE_UNAVAILABLE`; MUST be NULL when `observation_status=SKIPPED_CONFIGURATION_UNAVAILABLE` (see Conditional Nullability) | immutable |
| `primary_latest_candle_ts_utc` | `DATETIME(6)` | no | materializer runtime | Latest persisted primary candle close timestamp used | immutable |
| `supporting_latest_candle_ts_utc` | `DATETIME(6)` | no | materializer runtime | Latest persisted supporting candle close timestamp used | immutable |
| `primary_source_age_seconds` | `INT UNSIGNED` | no | materializer runtime | Age of latest primary candle at observation time | immutable |
| `supporting_source_age_seconds` | `INT UNSIGNED` | no | materializer runtime | Age of latest supporting candle at observation time | immutable |
| `primary_source_freshness_limit_seconds` | `INT UNSIGNED` | yes* | materializer runtime | Freshness bound used for primary interval; MUST be NULL when `observation_status=SKIPPED_CONFIGURATION_UNAVAILABLE` (see Conditional Nullability) | immutable |
| `supporting_source_freshness_limit_seconds` | `INT UNSIGNED` | yes* | materializer runtime | Freshness bound used for supporting interval; MUST be NULL when `observation_status=SKIPPED_CONFIGURATION_UNAVAILABLE` (see Conditional Nullability) | immutable |
| `context_status` | `VARCHAR(96)` | no | materializer runtime | Native SHORT context status from context builder | immutable |
| `current_map_id_before` | `BIGINT UNSIGNED` | no | materializer runtime | Active map id before evaluation | immutable |
| `current_map_id_after` | `BIGINT UNSIGNED` | no | materializer runtime | Active/current map id after evaluation and transition handling | immutable |
| `published_map_id` | `BIGINT UNSIGNED` | no | materializer runtime | New map id when geometry was published | immutable |
| `generation_attempt_id` | `CHAR(36)` | no | materializer runtime | Generation attempt id when generation ledger was touched | immutable |
| `generation_event_id` | `BIGINT UNSIGNED` | no | materializer runtime | Terminal generation event id for this observation, if any | immutable |
| `lifecycle_event_id` | `BIGINT UNSIGNED` | no | materializer runtime | Lifecycle transition event id appended by this observation, if any | immutable |
| `lifecycle_state_before` | `VARCHAR(64)` | no | materializer runtime | Derived lifecycle state before observation | immutable |
| `lifecycle_state_after` | `VARCHAR(64)` | no | materializer runtime | Derived lifecycle state after observation | immutable |
| `geometry_action` | `VARCHAR(64)` | yes* | materializer runtime | `PUBLISHED_NEW_MAP`, `UNCHANGED_GEOMETRY`, `REJECTED_CONTEXT`, or `NO_MAP_AVAILABLE`; MUST be NULL when `observation_status=SKIPPED_CONFIGURATION_UNAVAILABLE` (see Conditional Nullability) | immutable |
| `structure_hash` | `CHAR(64)` | no | materializer runtime | Map structure hash evaluated for idempotency | immutable |
| `source_primary_candle_count` | `INT UNSIGNED` | no | materializer runtime | Primary candles available to context builder | immutable |
| `source_support_candle_count` | `INT UNSIGNED` | no | materializer runtime | Supporting candles available to context builder | immutable |
| `created_at_utc` | `DATETIME(6)` | yes | materializer runtime | Row creation timestamp | immutable |

### Conditional Nullability: `SKIPPED_CONFIGURATION_UNAVAILABLE`

Fields marked `yes*` above are required for every other `observation_status`
value and MUST be NULL only when `observation_status=SKIPPED_CONFIGURATION_UNAVAILABLE`.
For that status:

- `observation_reason_code` MUST equal `NO_ELIGIBLE_CADENCE_CONFIG`.
- `cadence_contract_version` MUST be NULL.
- `primary_source_freshness_limit_seconds` MUST be NULL.
- `supporting_source_freshness_limit_seconds` MUST be NULL.
- `source_state` MUST be NULL.
- `geometry_action` MUST be NULL.
- `evaluation_due_at_utc` MUST be NULL.
- No candle freshness calculation, map-generation evaluation, or lifecycle
  transition attempt is made for this observation. `current_map_id_before`,
  `current_map_id_after`, `published_map_id`, `generation_attempt_id`,
  `generation_event_id`, `lifecycle_event_id`, `lifecycle_state_before`, and
  `lifecycle_state_after` remain NULL for this observation, consistent with no
  evaluation having started.
- The row is still append-only evidence that the scope was considered by the
  run and evaluation was blocked before any cadence-dependent step began.

For every other `observation_status` value, the existing non-null requirements
on `cadence_contract_version`, `source_state`, both freshness-limit fields, and
`geometry_action` remain in force unchanged; NULL in these fields is invalid
for any status other than `SKIPPED_CONFIGURATION_UNAVAILABLE`.

PR A1b must relax the `NOT NULL` constraints on exactly these MariaDB columns
for `native_short_scope_observation_v1`, and add a `CHECK` constraint (or
equivalent) that permits NULL in these columns only when
`observation_status='SKIPPED_CONFIGURATION_UNAVAILABLE'` and requires
non-NULL otherwise. This migration is not written in this docs-only amendment.

## Entity: native_short_scope_support_event_v1

Purpose: append-only provenance for native SHORT scope support-state changes over
time. This event ledger is required because the existing
`native_short_map_scope_v1` table is a mutable current registry with
`created_at_utc` and `updated_at_utc`, but no append-only support-state history.

Relationship to `native_short_map_scope_v1`:

- `native_short_map_scope_v1` remains the mutable current scope registry for
  ordinary live operation.
- `native_short_map_scope_v1` is not authoritative for historical `as_of_utc`
  reconstruction.
- Do not use `updated_at_utc` as historical support-state evidence.
- PR A1 migration must backfill exactly one initial support event per existing
  scope, with state copied from the current registry.
- The backfill event timestamp must be an explicitly documented
  migration/backfill timestamp.
- Historical support state before the backfill timestamp is `UNKNOWN`, not
  inferred.
- Do not invent historical support transitions from `updated_at_utc`.

Mutability: append-only. Rows are inserted only; no updates are allowed.

Retention: permanent provenance. These rows are required for cutoff-aware
projection and future historical replay.

Keys and indexes:

- Primary key: `scope_support_event_id`.
- Index: full canonical scope key plus `(event_ts_utc, scope_support_event_id)`.
- Index: full canonical scope key plus `(scope_support_state, event_ts_utc)`.
- Deterministic support-state tie-breaker: `event_ts_utc`, then
  `scope_support_event_id`.
- Exact full-key identity only. No symbol-only lookup.

Allowed V1 support states:

```text
SUPPORTED
NOT_APPLICABLE
```

Fields:

| Field | Type intent for MariaDB | Required | Writer | Meaning | Mutability |
|---|---|---:|---|---|---|
| `scope_support_event_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | yes | MariaDB | Surrogate event id and deterministic tie-breaker | immutable |
| `venue` | `VARCHAR(32)` | yes | scope support writer / A1 backfill | Canonical scope key | immutable |
| `symbol` | `VARCHAR(32)` | yes | scope support writer / A1 backfill | Canonical scope key | immutable |
| `quote_currency` | `VARCHAR(16)` | yes | scope support writer / A1 backfill | Canonical scope key | immutable |
| `fib_trading_horizon` | `VARCHAR(32)` | yes | scope support writer / A1 backfill | Canonical scope key; `SHORT` is tactical horizon | immutable |
| `primary_interval` | `VARCHAR(16)` | yes | scope support writer / A1 backfill | Canonical scope key | immutable |
| `supporting_interval` | `VARCHAR(16)` | yes | scope support writer / A1 backfill | Canonical scope key | immutable |
| `scope_support_state` | `VARCHAR(32)` | yes | scope support writer / A1 backfill | `SUPPORTED` or `NOT_APPLICABLE` | immutable |
| `event_ts_utc` | `DATETIME(6)` | yes | scope support writer / A1 backfill | Authoritative timestamp for support-state change | immutable |
| `reason_code` | `VARCHAR(64)` | no | scope support writer / A1 backfill | Stable reason for the support-state event | immutable |
| `reason_detail` | `VARCHAR(255)` | no | scope support writer / A1 backfill | Bounded non-secret detail | immutable |
| `source_name` | `VARCHAR(96)` | yes | scope support writer / A1 backfill | Source that created the event | immutable |
| `source_version` | `VARCHAR(32)` | yes | scope support writer / A1 backfill | Source version that created the event | immutable |
| `event_metadata_json` | `JSON` or `LONGTEXT` | no | scope support writer / A1 backfill | Optional deterministic metadata payload | immutable |
| `created_at_utc` | `DATETIME(6)` | yes | scope support writer / A1 backfill | Row creation timestamp | immutable |

## Entity: native_short_scope_status_v1

Purpose: rebuildable current market projection with exactly one canonical row per
SUPPORTED scope. It is a display/reporting and health input, not a decision gate
and not execution intent.

Mutability: rebuildable projection. Rows may be deleted and rebuilt, or upserted
from authoritative sources, as long as the resulting contents are deterministic.
The table is not authoritative history.

Retention: current-row projection only. Historical status is reconstructed from
run, observation, map, generation, lifecycle, and candle facts.

Projection time contract:

- Every projection rebuild accepts an explicit UTC `as_of_utc`.
- `as_of_utc` is the sole clock used for source freshness, observation overdue
  calculation, recently-added-scope grace, next expected evaluation, and
  overdue-after calculation.
- Deterministic projection logic must not call implicit `datetime.now()` or
  database `NOW()`.
- `native_short_scope_status_v1` includes
  `projection_as_of_utc DATETIME(6) NOT NULL`.
- Live runtime supplies explicit current UTC once per bounded run.
- Future replay supplies its virtual historical clock as `as_of_utc`. This
  contract does not implement replay.
- `rebuilt_at_utc` is operational metadata only and must not affect semantic
  status output.

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
| `observation_freshness_state` | `VARCHAR(64)` | yes | projection rebuild process | `OBSERVATION_CURRENT`, `OBSERVATION_OVERDUE`, `NO_OBSERVATION`, or `OBSERVATION_CONFIGURATION_UNAVAILABLE` | rebuildable |
| `source_freshness_state` | `VARCHAR(64)` | yes* | projection rebuild process | `SOURCE_CURRENT`, `SOURCE_STALE`, or `SOURCE_UNAVAILABLE`; MUST be NULL when `scope_status_code=CONFIGURATION_UNAVAILABLE` (see Conditional Nullability) | rebuildable |
| `actionability_state` | `VARCHAR(64)` | yes | projection rebuild process | Human-safe market-only actionability classification | rebuildable |
| `current_map_id` | `BIGINT UNSIGNED` | no | projection rebuild process | Deterministically selected current map id, or NULL when no current map exists | rebuildable |
| `current_map_cycle_id` | `VARCHAR(255)` | no | projection rebuild process | Map cycle id for the current map | rebuildable |
| `current_map_published_at_utc` | `DATETIME(6)` | no | projection rebuild process | Immutable map publication timestamp | rebuildable |
| `current_map_structure_hash` | `CHAR(64)` | no | projection rebuild process | Current map structure hash | rebuildable |
| `latest_generation_event_id` | `BIGINT UNSIGNED` | no | projection rebuild process | Latest authoritative generation event for scope | rebuildable |
| `latest_lifecycle_event_id` | `BIGINT UNSIGNED` | no | projection rebuild process | Latest lifecycle event for current map | rebuildable |
| `latest_observation_id` | `BIGINT UNSIGNED` | no | projection rebuild process | Latest scope observation used | rebuildable |
| `latest_run_id` | `BIGINT UNSIGNED` | no | projection rebuild process | Parent run for latest observation | rebuildable |
| `latest_observed_at_utc` | `DATETIME(6)` | no | projection rebuild process | Last scope observation timestamp | rebuildable |
| `next_expected_evaluation_at_utc` | `DATETIME(6)` | no | projection rebuild process | Next expected evaluation under cadence contract; MUST be NULL when `scope_status_code=CONFIGURATION_UNAVAILABLE` | rebuildable |
| `observation_overdue_after_utc` | `DATETIME(6)` | no | projection rebuild process | Time after which observation becomes overdue; MUST be NULL when `scope_status_code=CONFIGURATION_UNAVAILABLE` | rebuildable |
| `primary_latest_candle_ts_utc` | `DATETIME(6)` | no | projection rebuild process | Latest primary candle timestamp used for current source state | rebuildable |
| `supporting_latest_candle_ts_utc` | `DATETIME(6)` | no | projection rebuild process | Latest supporting candle timestamp used for current source state | rebuildable |
| `primary_source_freshness_limit_seconds` | `INT UNSIGNED` | yes* | projection rebuild process | Active primary source freshness bound; MUST be NULL when `scope_status_code=CONFIGURATION_UNAVAILABLE` (see Conditional Nullability) | rebuildable |
| `supporting_source_freshness_limit_seconds` | `INT UNSIGNED` | yes* | projection rebuild process | Active supporting source freshness bound; MUST be NULL when `scope_status_code=CONFIGURATION_UNAVAILABLE` (see Conditional Nullability) | rebuildable |
| `cadence_contract_version` | `VARCHAR(32)` | yes* | projection rebuild process | Cadence/grace config version applied; MUST be NULL when `scope_status_code=CONFIGURATION_UNAVAILABLE` (see Conditional Nullability) | rebuildable |
| `projection_as_of_utc` | `DATETIME(6)` | yes | projection rebuild process | Explicit semantic clock used for projection calculations | rebuildable |
| `status_payload_json` | `JSON` | no | projection rebuild process | Bounded deterministic diagnostics for reporting; when `scope_status_code=CONFIGURATION_UNAVAILABLE`, must contain enough detail to explain which exact full-key config version window was expected and absent | rebuildable |
| `rebuilt_at_utc` | `DATETIME(6)` | yes | projection rebuild process | Operational projection rebuild timestamp; not semantic input | rebuildable |

### Conditional Nullability: `CONFIGURATION_UNAVAILABLE`

Fields marked `yes*` above are required for every other `scope_status_code`
value and MUST be NULL only when `scope_status_code=CONFIGURATION_UNAVAILABLE`.
For that status:

- `scope_status_reason_code` MUST equal `NO_ELIGIBLE_CADENCE_CONFIG`.
- `actionability_state` MUST equal `BLOCKED_CONFIGURATION`.
- `observation_freshness_state` MUST equal `OBSERVATION_CONFIGURATION_UNAVAILABLE`.
- `cadence_contract_version` MUST be NULL.
- `primary_source_freshness_limit_seconds` MUST be NULL.
- `supporting_source_freshness_limit_seconds` MUST be NULL.
- `source_freshness_state` MUST be NULL, because source freshness cannot be
  classified without the missing configured thresholds.
- `next_expected_evaluation_at_utc` and `observation_overdue_after_utc` MUST be
  NULL, because both depend on the missing cadence/grace configuration.
- `map_lifecycle_state`, `current_map_id`, `current_map_cycle_id`,
  `current_map_published_at_utc`, `current_map_structure_hash`,
  `latest_generation_event_id`, and `latest_lifecycle_event_id` are unaffected
  by missing cadence config and continue to reflect independently known map and
  lifecycle facts eligible at `as_of_utc` (see Projection Rebuild Contract).
- `latest_observation_id`, `latest_run_id`, and `latest_observed_at_utc` MAY
  reference the `SKIPPED_CONFIGURATION_UNAVAILABLE` observation for this scope
  and run.

For every other `scope_status_code` value, the existing non-null requirements
on `cadence_contract_version`, both freshness-limit fields, and
`source_freshness_state` remain in force unchanged; NULL in these fields is
invalid for any status other than `CONFIGURATION_UNAVAILABLE`.

PR A1b must relax the `NOT NULL` constraints on exactly these MariaDB columns
for `native_short_scope_status_v1`, and add a `CHECK` constraint (or
equivalent) that permits NULL in these columns only when
`scope_status_code='CONFIGURATION_UNAVAILABLE'` and requires non-NULL
otherwise. This migration is not written in this docs-only amendment.

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

V1 cadence config is exact full canonical scope key only. Wildcard/default
inheritance is out of scope until separately specified.

### Eligibility And The `NO_ELIGIBLE_CADENCE_CONFIG` Reason Code

A cadence config version is eligible at a given `as_of_utc` only when:

```text
effective_from_utc <= as_of_utc
AND (effective_to_utc IS NULL OR effective_to_utc > as_of_utc)
```

When no version for the scope's exact full key satisfies this window at
`as_of_utc`, the scope is in the `NO_ELIGIBLE_CADENCE_CONFIG` configuration
state. This is configuration state, never candle/source state: it MUST NOT be
represented as `SOURCE_UNAVAILABLE`, `SOURCE_STALE`, or `OBSERVATION_OVERDUE`,
and it MUST NOT be papered over with an invented version string or fabricated
freshness limits. See Status Precedence and Projection Rebuild Contract for the
resulting `CONFIGURATION_UNAVAILABLE` top-level status and the observation-side
`SKIPPED_CONFIGURATION_UNAVAILABLE` status.

Required configuration fields:

| Field | Type intent for MariaDB | Required | Writer | Meaning | Mutability |
|---|---|---:|---|---|---|
| `cadence_config_id` | `BIGINT UNSIGNED AUTO_INCREMENT` | yes | migration/config owner | Surrogate config id | immutable |
| `venue` | `VARCHAR(32)` | yes | migration/config owner | Exact canonical scope key | immutable per version |
| `symbol` | `VARCHAR(32)` | yes | migration/config owner | Exact canonical scope key | immutable per version |
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

### Canonical Native SHORT V1 Cadence Profile

The config owner has authorized the following as the first canonical native
SHORT cadence/grace profile, seeded via exact full-key rows only (no
wildcard/default inheritance) for every scope that is `SUPPORTED` at
`fib_trading_horizon=SHORT`:

| Field | Value | Rationale |
|---|---|---|
| `cadence_contract_version` | `native_short_cadence_v1` | First canonical version label for this profile. |
| `primary_interval` | `4h` | Canonical scope key; matches native default above. |
| `supporting_interval` | `1h` | Canonical scope key; matches native default above. |
| `target_evaluation_interval` | `1h` | Matches native default above. |
| `primary_source_freshness_limit_seconds` | `43200` (12h) | Matches native default above, expressed in seconds. |
| `supporting_source_freshness_limit_seconds` | `10800` (3h) | Matches native default above, expressed in seconds. |
| `evaluation_grace_seconds` | `900` (15m) | 15 minutes after the expected persisted closed 1h candle before overdue classification. |
| `recent_scope_grace_seconds` | `3600` (1h) | One full 1h cycle of grace for newly supported scopes before overdue classification. |

These are explicit config-owner defaults, not inferred from test fixtures.
The seed migration (`db/migrations/20260709_native_short_cadence_v1_seed.sql`)
inserts one exact full-key row per currently `SUPPORTED` native SHORT scope
using this profile.

## Status Precedence

`native_short_scope_status_v1.scope_status_code` is a single canonical code. The
projection may expose separate lifecycle, observation freshness, source
freshness, and actionability fields, but the top-level code must be deterministic
when multiple conditions exist.

`native_short_scope_status_v1` is strictly one row per SUPPORTED scope,
including a SUPPORTED scope that is configuration-blocked. No status row
exists for a non-SUPPORTED scope. Unsupported or not-applicable reporting is
scope-inventory or health-report information derived directly from
`native_short_map_scope_v1`, not a scope-status projection row. A missing
cadence config is not grounds to omit the row: omitting it would make a
configuration defect indistinguishable from an unsupported or
`UNKNOWN_AT_AS_OF` scope, which defeats the purpose of A3 health reporting
consuming this projection.

Precedence from highest to lowest:

1. `CONFIGURATION_UNAVAILABLE`
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
| `CONFIGURATION_UNAVAILABLE` | No exact full-key cadence configuration is eligible at `as_of_utc` (see `NO_ELIGIBLE_CADENCE_CONFIG`). This is a configuration defect, not market-data unavailability, market-data staleness, map lifecycle state, or runtime observation cadence. It outranks every other code because no other field can be trusted to reflect current freshness or cadence without a configured version. |
| `SOURCE_UNAVAILABLE` | Required persisted candle source data is absent or insufficient to determine current source freshness. This is about market input availability, not runtime cadence. |
| `SOURCE_STALE` | Required candle source exists but latest primary or supporting candle violates its configured freshness bound. This is market-data staleness, even if the runtime ran on time. |
| `MAP_INVALIDATED` | Current map has a terminal invalidation lifecycle event. Lifecycle terminal state outranks overdue observation because the map is no longer active. |
| `MAP_COMPLETED` | Current map has a terminal completed lifecycle event. Lifecycle terminal state outranks overdue observation because the map already reached terminal success. |
| `SCOPE_RECENTLY_ADDED` | Scope is SUPPORTED but is still within configured recent-scope grace and lacks sufficient observation history. This prevents immediate false overdue alerts. |
| `OBSERVATION_OVERDUE` | Candle source is available/current enough, but the latest materializer observation is missing or older than the expected cadence plus grace. This is runtime observation staleness, not candle staleness. |
| `CURRENT_EVALUATION` | Scope is SUPPORTED, source is available/current, observation is within cadence/grace, and map lifecycle is non-terminal or no map exists yet. |

Lifecycle state versus observation/freshness state:

- `map_lifecycle_state` describes the selected current map only: active,
  invalidated, completed, expired, or `NO_CURRENT_MAP`. It is derived only from
  the map and lifecycle-event ledgers and does not depend on cadence config, so
  it remains populated with the real, independently known value even when
  `scope_status_code=CONFIGURATION_UNAVAILABLE`.
- `observation_freshness_state` describes whether the materializer evaluated the
  scope within the cadence/grace contract, or `OBSERVATION_CONFIGURATION_UNAVAILABLE`
  when no cadence config was eligible to evaluate against.
- `source_freshness_state` describes persisted candle availability and age, or
  is NULL when `scope_status_code=CONFIGURATION_UNAVAILABLE` because the
  freshness bound needed to classify it is itself missing.
- These states are stored separately because a terminal map can be fresh, stale,
  or overdue, and a current observation can still report stale source data.

Actionability state:

- `BLOCKED_CONFIGURATION`: no eligible cadence configuration exists for the
  scope at `as_of_utc`; nothing about source, map, or observation freshness can
  be classified until a configuration version is added.
- `ACTIONABLE_ACTIVE_MAP`: non-terminal current map, current source, current observation.
- `NO_ACTIONABLE_MAP`: no current map exists, but the scope is otherwise current.
- `TERMINAL_MAP`: selected current map is completed, invalidated, or expired.
- `BLOCKED_SOURCE`: source is stale or unavailable.
- `BLOCKED_OBSERVATION`: runtime observation is overdue.
- `BLOCKED_SCOPE`: SUPPORTED scope is recently added inside grace and lacks
  sufficient observation history.

When multiple conditions exist, the canonical current row stores the highest
precedence `scope_status_code`, while the separate state fields preserve the
lower-precedence facts. Example: if source data is stale and the latest
observation is overdue, the canonical code is `SOURCE_STALE`, with
`observation_freshness_state=OBSERVATION_OVERDUE`.

Exact stale-versus-overdue-versus-configuration distinction:

- `CONFIGURATION_UNAVAILABLE` means no exact full-key cadence configuration
  version is eligible at `as_of_utc`. It is orthogonal to candle data and to
  runtime cadence: a scope with perfectly fresh candles and a perfectly on-time
  materializer is still `CONFIGURATION_UNAVAILABLE` if no config version
  covers `as_of_utc`. It must never be reported as `SOURCE_UNAVAILABLE`,
  `SOURCE_STALE`, or `OBSERVATION_OVERDUE`, all of which presuppose a
  configured freshness bound or cadence that does not exist in this case.
- `SOURCE_STALE` means the persisted 4h or 1h candle input is too old under the
  configured source freshness bound.
- `OBSERVATION_OVERDUE` means the materializer did not produce a recent enough
  scope observation under the configured evaluation cadence/grace while source
  data is available and not stale.

## Projection Rebuild Contract

Authoritative inputs:

- `native_short_map_scope_v1` for live/current scope inventory only
- `native_short_scope_support_event_v1` for cutoff/historical support-state provenance
- cadence/grace configuration owner
- `native_short_materializer_run_v1`
- `native_short_scope_observation_v1`
- `native_short_map_v1`
- `native_short_map_generation_event_v1`
- `native_short_map_lifecycle_event_v1`
- persisted primary and supporting candles

As-of knowledge-cutoff invariant:

```text
Projection state at T may depend only on persisted facts with authoritative timestamps <= T.
```

Every authoritative input used for one projection row must be eligible at or
before that rebuild's explicit `as_of_utc`. This applies equally to live bounded
runs, where `as_of_utc` is current explicit UTC, and future historical replay,
where `as_of_utc` is virtual historical UTC.

Eligibility rules:

- Scope inventory: for live/current projection, the current scope registry may
  be used as the source of current scope inventory. For cutoff/historical
  projection, select the latest eligible scope-support event with
  `event_ts_utc <= as_of_utc`, ordered by `event_ts_utc DESC,
  scope_support_event_id DESC`. Only scopes whose selected event is `SUPPORTED`
  receive a projection row. If no eligible support event exists, no projection
  row is created and scope support is `UNKNOWN_AT_AS_OF`; this is
  inventory/history evidence, not a projection status code. Do not use a scope
  support change that occurred after `as_of_utc`, and do not use current
  registry `updated_at_utc` as historical evidence.
- Cadence configuration: select only the exact full-key config version effective
  at `as_of_utc`: `effective_from_utc <= as_of_utc` and
  `effective_to_utc IS NULL OR effective_to_utc > as_of_utc`. Do not use a
  future configuration version. A config version that only becomes eligible
  after `as_of_utc` must never satisfy an earlier `as_of_utc`. If no version is
  eligible, the scope is `NO_ELIGIBLE_CADENCE_CONFIG` (see Cadence And Grace
  Configuration Ownership) and the status row MUST be written with
  `scope_status_code=CONFIGURATION_UNAVAILABLE` per Status Precedence; this is
  a configuration-state failure, never a source-availability, source-staleness,
  or observation-cadence failure, and must never be reported as
  `SOURCE_UNAVAILABLE`, `SOURCE_STALE`, or `OBSERVATION_OVERDUE`. Once a
  version becomes eligible for a later `as_of_utc`, normal cadence/source
  evaluation resumes for that later projection.
- Maps: only maps with `published_at_utc <= as_of_utc` are eligible for
  current-map selection. Apply supersession exclusion only from `SUPERSEDED`
  lifecycle events with `event_ts_utc <= as_of_utc`.
- Lifecycle: resolve selected-map lifecycle only from lifecycle events with
  `event_ts_utc <= as_of_utc`. Continue using `(event_ts_utc,
  lifecycle_event_id)` tie-break order.
- Generation provenance: latest generation event must be limited to events known
  at `as_of_utc`, using persisted `event_ts_utc <= as_of_utc`, then
  `generation_event_id` as deterministic tie-breaker.
- Observations: latest scope observation must satisfy
  `observed_at_utc <= as_of_utc`. A future observation must never make an
  earlier projection look current.
- Candles: latest primary and supporting candle timestamps used for source
  freshness must satisfy `close_ts_utc <= as_of_utc`. Never use future candle
  rows relative to the projection clock.
- Failure behavior: if no eligible cadence config exists at `as_of_utc`,
  projection rebuild fails closed for that scope by writing
  `scope_status_code=CONFIGURATION_UNAVAILABLE` with
  `scope_status_reason_code=NO_ELIGIBLE_CADENCE_CONFIG` (see Status
  Precedence). A status row MUST still be written for the scope; omitting the
  row is not permitted, since an absent row is reserved for non-SUPPORTED and
  `UNKNOWN_AT_AS_OF` scopes and would make a configuration defect
  indistinguishable from those cases. Do not silently use the latest current
  config. If source data exists only after `as_of_utc`, classify it as
  unavailable at that projection time.

Deterministic rebuild ordering for each canonical scope:

1. Accept explicit UTC `as_of_utc`; do not read wall-clock time inside projection logic.
2. For live/current projection, load current SUPPORTED scope rows from `native_short_map_scope_v1` using full key ordering. For cutoff/historical projection, derive SUPPORTED scope rows from latest eligible `native_short_scope_support_event_v1` events at `as_of_utc`.
3. Load active cadence/grace config by full key and effective timestamp at `as_of_utc`.
4. Load latest eligible scope observation by `(observed_at_utc, scope_observation_id)`.
5. Select the current map by the deterministic current-map selection rule below.
6. Load latest eligible generation event by `(event_ts_utc, generation_event_id)` for the scope.
7. Resolve lifecycle state only for the selected map using its latest eligible lifecycle event by `(event_ts_utc, lifecycle_event_id)`.
8. Load latest eligible primary and supporting candle timestamps.
9. Compute source freshness, observation freshness, lifecycle state, actionability, and top-level status by precedence using `as_of_utc`.
10. Write exactly one projection row for the SUPPORTED scope.

Configuration-unavailable rebuild ordering (applies when step 3 finds no
eligible cadence config for an otherwise-SUPPORTED scope):

- Steps 5–7 (current-map selection and lifecycle resolution) still run
  normally: they depend only on the map and lifecycle-event ledgers, not on
  cadence config, and populate `current_map_id`, `map_lifecycle_state`, and
  related fields with their real, independently known values.
- Step 4 (latest eligible scope observation) still runs; observation lookup
  does not depend on cadence config, and may resolve to a
  `SKIPPED_CONFIGURATION_UNAVAILABLE` observation for this scope and run.
- Step 8 (candle timestamp loading) and the source-freshness classification
  half of step 9 do not run: no `SOURCE_CURRENT` / `SOURCE_STALE` /
  `SOURCE_UNAVAILABLE` classification is attempted, and
  `source_freshness_state` is left NULL.
- Step 9's top-level status computation short-circuits to
  `scope_status_code=CONFIGURATION_UNAVAILABLE`,
  `actionability_state=BLOCKED_CONFIGURATION`, and
  `observation_freshness_state=OBSERVATION_CONFIGURATION_UNAVAILABLE`,
  overriding every other precedence input, including the `MAP_EXPIRED`
  fall-through described in Required Behavior below.
- Step 10 still writes exactly one projection row for the scope; the row is
  never omitted.

Current-map selection rule:

1. First identify maps superseded by a later authoritative `SUPERSEDED`
   lifecycle event and exclude them from current-map selection.
2. Among remaining maps, choose the latest map by `published_at_utc`, then
   `map_id` as deterministic tie-breaker.
3. Resolve lifecycle state only for that selected map using its latest lifecycle
   event by `event_ts_utc`, then `lifecycle_event_id` as deterministic
   tie-breaker.
4. A terminal older map must never override a newer non-terminal selected map.
5. `current_map_id`, lifecycle state, actionability, and top-level status derive
   only from the selected map.
6. If no non-superseded map exists because all maps are superseded, set
   `map_lifecycle_state=NO_CURRENT_MAP` and `current_map_id=NULL`; source and
   observation precedence still applies.

Idempotency:

- Rebuilding the projection from unchanged authoritative inputs plus identical
  `as_of_utc` must produce identical semantic rows.
- `rebuilt_at_utc` may differ between otherwise identical semantic rebuilds.
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

- One canonical row exists per SUPPORTED scope at the chosen `as_of_utc`,
  including a scope that is configuration-blocked. Configuration-blocked
  status is an operationally relevant defect signal for A3 health reporting,
  not a reason to omit the row.
- No status row exists for a non-SUPPORTED or `UNKNOWN_AT_AS_OF` scope.
- `SCOPE_NOT_APPLICABLE` remains excluded from projection status codes.
- If no eligible cadence config exists for an otherwise-SUPPORTED scope at
  `as_of_utc`, `scope_status_code=CONFIGURATION_UNAVAILABLE` overrides every
  other precedence input (source, map lifecycle, observation), per Status
  Precedence. This is the only status above `SOURCE_UNAVAILABLE` in precedence.
- If no selected map exists, set `map_lifecycle_state=NO_CURRENT_MAP` and use `CURRENT_EVALUATION`
  only when source and observation are current; otherwise apply source/observation
  precedence.
- If latest observation failed, preserve the failure reason in
  `scope_status_reason_code` and status payload. Classify by source state first,
  then overdue/current observation rules, unless the failure proves
  `SOURCE_UNAVAILABLE`.
- If the selected map is terminal, set `MAP_INVALIDATED` or `MAP_COMPLETED` when
  applicable. Expired terminal maps use `map_lifecycle_state=EXPIRED` plus
  `actionability_state=TERMINAL_MAP` and source/observation precedence unless a
  higher explicit terminal status is later added to this contract.
  `CONFIGURATION_UNAVAILABLE` is such a higher-precedence status: when no
  eligible cadence config exists, it overrides the `EXPIRED` fall-through
  regardless of the selected map's lifecycle state.
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
- A configuration-blocked evaluation (no eligible cadence config; observation
  status `SKIPPED_CONFIGURATION_UNAVAILABLE`) must not attempt map generation,
  must not publish a map, must not emit a generation event, and must not
  attempt or append a lifecycle transition event for that scope in that run.

## Migration And Rollout Plan

### PR A1 — Migrations And Types Only

- Add MariaDB migrations only for the persistence contract.
- Include migration for `native_short_scope_support_event_v1`.
- Backfill exactly one initial support event per existing scope from the current
  scope registry, with a documented migration/backfill timestamp.
- Add model and validation types for run, observation, scope support event,
  cadence, and status rows.
- No materializer runner integration.
- No lifecycle transition detection.
- No health-report switch.
- No systemd, timer, wrapper, or runtime deployment.

### PR A1b — Configuration-Unavailable Schema/Type Change

- Narrow follow-up to PR A1, required by Amendment 1 above.
- Migration relaxes `NOT NULL` to conditional-nullable, exactly for:
  - `native_short_scope_observation_v1`: `cadence_contract_version`,
    `primary_source_freshness_limit_seconds`,
    `supporting_source_freshness_limit_seconds`, `source_state`,
    `geometry_action`.
  - `native_short_scope_status_v1`: `cadence_contract_version`,
    `primary_source_freshness_limit_seconds`,
    `supporting_source_freshness_limit_seconds`, `source_freshness_state`.
- Migration adds `CHECK` constraints (or equivalent) enforcing that the above
  columns are NULL only when `observation_status='SKIPPED_CONFIGURATION_UNAVAILABLE'`
  or `scope_status_code='CONFIGURATION_UNAVAILABLE'` respectively, and non-NULL
  for every other value.
- Migration extends the `observation_status`, `scope_status_code`,
  `actionability_state`, and `observation_freshness_state` `CHECK` constraints
  to include `SKIPPED_CONFIGURATION_UNAVAILABLE`, `CONFIGURATION_UNAVAILABLE`,
  `BLOCKED_CONFIGURATION`, and `OBSERVATION_CONFIGURATION_UNAVAILABLE`
  respectively.
- Validation-type updates (pure, no I/O) accept the new conditional-null
  combination for these two new enum values and continue to reject NULL in
  these fields for every other value.
- No materializer runner integration.
- No lifecycle transition detection.
- No health-report switch.
- No systemd, timer, wrapper, or runtime deployment.
- PR A2 must not begin implementation until PR A1b merges.

### PR A2 — Materializer Integration And Projection

- Depends on PR A1b.
- Record materializer run rows.
- Record per-scope observation rows, including
  `SKIPPED_CONFIGURATION_UNAVAILABLE` observations for scopes with no eligible
  cadence config.
- Implement projection rebuild logic for `native_short_scope_status_v1`,
  including the `CONFIGURATION_UNAVAILABLE` status row for scopes with no
  eligible cadence config.
- Use `native_short_scope_support_event_v1` for cutoff-aware projection
  selection.
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

- MariaDB migration defines run, observation, projection, scope support event,
  and cadence/grace persistence using the full canonical scope key.
- Migration includes `native_short_scope_support_event_v1`.
- Migration performs an initial explicit backfill from existing scope registry:
  exactly one event per existing scope, current state copied from the registry,
  and a documented migration/backfill timestamp.
- Migration tests or SQL inspections prove required keys and indexes exist.
- Model/validation tests cover scope support events and reject symbol-only identity.
- Tests prove current registry updates are not used as historical evidence.
- Tests prove support-state selection is cutoff bounded.
- Tests prove same-timestamp support events resolve by `scope_support_event_id`.
- Tests prove absent pre-backfill history yields `UNKNOWN_AT_AS_OF`, not inferred
  support.
- No runner code imports or writes the new tables.
- No health report reads the new projection.
- No scheduler, service, timer, wrapper, broker, execution, or UI files change.

PR A1b acceptance:

- Migration relaxes `NOT NULL` to conditional-nullable exactly for the columns
  listed in PR A1b of the Migration And Rollout Plan, on
  `native_short_scope_observation_v1` and `native_short_scope_status_v1` only.
- Migration/`CHECK` constraints prove the relaxed columns accept NULL only for
  `observation_status='SKIPPED_CONFIGURATION_UNAVAILABLE'` or
  `scope_status_code='CONFIGURATION_UNAVAILABLE'`, and reject NULL for every
  other value.
- `observation_status`, `scope_status_code`, `actionability_state`, and
  `observation_freshness_state` enums/`CHECK` constraints include the four new
  values defined in Amendment 1.
- Validation-type tests prove the new conditional-null combination is accepted
  only for the configuration-unavailable state and rejected for every other
  state (null cadence/source/geometry fields remain invalid elsewhere).
- No materializer runner integration change.
- No health-report switch.
- No scheduler, service, timer, wrapper, broker, execution, or UI files change.

PR A2 acceptance:

- Tests prove each materializer run writes one run record and deterministic
  per-scope observation records.
- Tests prove unchanged geometry does not publish duplicate maps and does not emit
  generation-event heartbeat rows.
- Tests prove unchanged geometry can still append exactly one real lifecycle
  transition event.
- Tests prove projection rebuild is idempotent from authoritative inputs.
- Tests prove projection selection uses `native_short_scope_support_event_v1` for
  cutoff/historical support-state reconstruction.
- Tests cover no-map, failed-observation, terminal-map, source-stale,
  source-unavailable, observation-overdue, and recently-added-scope cases.
- Tests prove a scope with no eligible cadence config produces exactly one
  append-only `SKIPPED_CONFIGURATION_UNAVAILABLE` observation for that
  scope/run.
- Tests prove a scope with no eligible cadence config produces exactly one
  `CONFIGURATION_UNAVAILABLE` status row, never omitted.
- Tests prove the no-eligible-config state never appears as
  `SOURCE_UNAVAILABLE`, `SOURCE_STALE`, or `OBSERVATION_OVERDUE`.
- Tests prove an eligible future cadence config version does not satisfy an
  earlier `as_of_utc`, and that normal cadence/source evaluation resumes for a
  scope once a config version becomes eligible.
- Tests prove no map, generation event, or lifecycle event is written during a
  configuration-blocked evaluation.
- Tests prove reporting can distinguish a SUPPORTED, configuration-blocked
  scope from an unsupported scope and from an `UNKNOWN_AT_AS_OF` scope.
- No systemd, timer, wrapper, broker, execution, or UI files change.
- PR A2 depends on PR A1b having merged first.

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
