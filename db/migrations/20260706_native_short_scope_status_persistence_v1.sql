-- Migration: native_short_scope_status_persistence_v1
-- Boundary: market-only persistent contract only
-- Purpose:
--   1. Persist native SHORT materializer run and per-scope observation evidence.
--   2. Persist exact full-key cadence configuration and current scope-status projection.
--   3. Add append-only support-state history for cutoff-aware projection.
-- Non-goals:
--   - no materializer runner integration
--   - no projection rebuild logic
--   - no health-report switch
--   - no deployment wiring
--   - no trading or presentation-layer changes

CREATE TABLE IF NOT EXISTS native_short_materializer_run_v1 (
    run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    run_uuid         CHAR(36)    NOT NULL,
    runner_name      VARCHAR(96) NOT NULL,
    runner_version   VARCHAR(32) NOT NULL,
    contract_version VARCHAR(32) NOT NULL,
    trigger_type     VARCHAR(64) NOT NULL,
    trigger_ref      VARCHAR(255) NULL,
    host_name        VARCHAR(128) NULL,
    process_id       INT UNSIGNED NULL,

    started_at_utc  DATETIME(6) NOT NULL,
    finished_at_utc DATETIME(6) NULL,
    terminal_status VARCHAR(32) NULL COMMENT 'FINISHED | FAILED | INTERRUPTED',

    requested_scope_count INT UNSIGNED NOT NULL,
    observed_scope_count  INT UNSIGNED NULL,
    published_map_count   INT UNSIGNED NULL,
    lifecycle_event_count INT UNSIGNED NULL,
    failed_scope_count    INT UNSIGNED NULL,

    failure_reason_code VARCHAR(96) NULL,
    failure_detail      TEXT NULL,

    created_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_native_short_materializer_run_v1_uuid (run_uuid),
    KEY idx_native_short_materializer_run_v1_started (started_at_utc),
    KEY idx_native_short_materializer_run_v1_runner_started (
        runner_name, runner_version, started_at_utc
    ),
    KEY idx_native_short_materializer_run_v1_terminal (
        terminal_status, finished_at_utc
    ),

    CONSTRAINT chk_native_short_materializer_run_v1_terminal
        CHECK (terminal_status IS NULL OR terminal_status IN ('FINISHED', 'FAILED', 'INTERRUPTED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only native SHORT materializer run evidence. Terminal fields are set once by future runtime integration.';


CREATE TABLE IF NOT EXISTS native_short_scope_observation_v1 (
    scope_observation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    run_id   BIGINT UNSIGNED NOT NULL,
    run_uuid CHAR(36) NOT NULL,

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL,
    fib_trading_horizon VARCHAR(32) NOT NULL,
    primary_interval    VARCHAR(16) NOT NULL,
    supporting_interval VARCHAR(16) NOT NULL,

    observed_at_utc          DATETIME(6) NOT NULL,
    evaluation_due_at_utc    DATETIME(6) NULL,
    cadence_contract_version VARCHAR(32) NOT NULL,

    observation_status      VARCHAR(64) NOT NULL COMMENT 'EVALUATED | FAILED | SKIPPED_SOURCE_UNAVAILABLE',
    observation_reason_code VARCHAR(96) NULL,
    observation_detail      TEXT NULL,
    source_state            VARCHAR(64) NOT NULL COMMENT 'SOURCE_CURRENT | SOURCE_STALE | SOURCE_UNAVAILABLE',

    primary_latest_candle_ts_utc    DATETIME(6) NULL,
    supporting_latest_candle_ts_utc DATETIME(6) NULL,
    primary_source_age_seconds      INT UNSIGNED NULL,
    supporting_source_age_seconds   INT UNSIGNED NULL,
    primary_source_freshness_limit_seconds    INT UNSIGNED NOT NULL,
    supporting_source_freshness_limit_seconds INT UNSIGNED NOT NULL,

    context_status        VARCHAR(96) NULL,
    current_map_id_before BIGINT UNSIGNED NULL,
    current_map_id_after  BIGINT UNSIGNED NULL,
    published_map_id      BIGINT UNSIGNED NULL,
    generation_attempt_id CHAR(36) NULL,
    generation_event_id   BIGINT UNSIGNED NULL,
    lifecycle_event_id    BIGINT UNSIGNED NULL,
    lifecycle_state_before VARCHAR(64) NULL,
    lifecycle_state_after  VARCHAR(64) NULL,
    geometry_action        VARCHAR(64) NOT NULL COMMENT 'PUBLISHED_NEW_MAP | UNCHANGED_GEOMETRY | REJECTED_CONTEXT | NO_MAP_AVAILABLE',
    structure_hash         CHAR(64) NULL,
    source_primary_candle_count INT UNSIGNED NULL,
    source_support_candle_count INT UNSIGNED NULL,

    created_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_native_short_scope_observation_v1_run_scope (
        run_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval
    ),
    KEY idx_native_short_scope_observation_v1_scope_observed (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval, observed_at_utc
    ),
    KEY idx_native_short_scope_observation_v1_run (run_id),
    KEY idx_native_short_scope_observation_v1_map (current_map_id_after),
    KEY idx_native_short_scope_observation_v1_status_time (observation_status, observed_at_utc),
    KEY idx_native_short_scope_observation_v1_source_time (source_state, observed_at_utc),

    CONSTRAINT fk_native_short_scope_observation_v1_run
        FOREIGN KEY (run_id) REFERENCES native_short_materializer_run_v1 (run_id),
    CONSTRAINT chk_native_short_scope_observation_v1_horizon
        CHECK (fib_trading_horizon = 'SHORT'),
    CONSTRAINT chk_native_short_scope_observation_v1_status
        CHECK (observation_status IN ('EVALUATED', 'FAILED', 'SKIPPED_SOURCE_UNAVAILABLE')),
    CONSTRAINT chk_native_short_scope_observation_v1_source
        CHECK (source_state IN ('SOURCE_CURRENT', 'SOURCE_STALE', 'SOURCE_UNAVAILABLE')),
    CONSTRAINT chk_native_short_scope_observation_v1_geometry
        CHECK (geometry_action IN ('PUBLISHED_NEW_MAP', 'UNCHANGED_GEOMETRY', 'REJECTED_CONTEXT', 'NO_MAP_AVAILABLE'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only per-scope native SHORT materializer observation evidence.';


CREATE TABLE IF NOT EXISTS native_short_scope_status_v1 (
    scope_status_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL,
    fib_trading_horizon VARCHAR(32) NOT NULL,
    primary_interval    VARCHAR(16) NOT NULL,
    supporting_interval VARCHAR(16) NOT NULL,

    scope_support_state VARCHAR(64) NOT NULL,
    scope_status_code   VARCHAR(64) NOT NULL COMMENT 'SOURCE_UNAVAILABLE | SOURCE_STALE | MAP_INVALIDATED | MAP_COMPLETED | SCOPE_RECENTLY_ADDED | OBSERVATION_OVERDUE | CURRENT_EVALUATION',
    scope_status_reason_code VARCHAR(96) NULL,
    map_lifecycle_state VARCHAR(64) NOT NULL,
    observation_freshness_state VARCHAR(64) NOT NULL COMMENT 'OBSERVATION_CURRENT | OBSERVATION_OVERDUE | NO_OBSERVATION',
    source_freshness_state VARCHAR(64) NOT NULL COMMENT 'SOURCE_CURRENT | SOURCE_STALE | SOURCE_UNAVAILABLE',
    actionability_state VARCHAR(64) NOT NULL COMMENT 'ACTIONABLE_ACTIVE_MAP | NO_ACTIONABLE_MAP | TERMINAL_MAP | BLOCKED_SOURCE | BLOCKED_OBSERVATION | BLOCKED_SCOPE',

    current_map_id BIGINT UNSIGNED NULL,
    current_map_cycle_id VARCHAR(255) NULL,
    current_map_published_at_utc DATETIME(6) NULL,
    current_map_structure_hash CHAR(64) NULL,
    latest_generation_event_id BIGINT UNSIGNED NULL,
    latest_lifecycle_event_id BIGINT UNSIGNED NULL,
    latest_observation_id BIGINT UNSIGNED NULL,
    latest_run_id BIGINT UNSIGNED NULL,
    latest_observed_at_utc DATETIME(6) NULL,
    next_expected_evaluation_at_utc DATETIME(6) NULL,
    observation_overdue_after_utc DATETIME(6) NULL,
    primary_latest_candle_ts_utc DATETIME(6) NULL,
    supporting_latest_candle_ts_utc DATETIME(6) NULL,
    primary_source_freshness_limit_seconds INT UNSIGNED NOT NULL,
    supporting_source_freshness_limit_seconds INT UNSIGNED NOT NULL,
    cadence_contract_version VARCHAR(32) NOT NULL,
    projection_as_of_utc DATETIME(6) NOT NULL,
    status_payload_json LONGTEXT NULL,
    rebuilt_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_native_short_scope_status_v1_scope (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval
    ),
    KEY idx_native_short_scope_status_v1_code (scope_status_code),
    KEY idx_native_short_scope_status_v1_actionability (actionability_state),
    KEY idx_native_short_scope_status_v1_observed (latest_observed_at_utc),
    KEY idx_native_short_scope_status_v1_map (current_map_id),

    CONSTRAINT chk_native_short_scope_status_v1_horizon
        CHECK (fib_trading_horizon = 'SHORT'),
    CONSTRAINT chk_native_short_scope_status_v1_support
        CHECK (scope_support_state = 'SUPPORTED'),
    CONSTRAINT chk_native_short_scope_status_v1_code
        CHECK (scope_status_code IN (
            'SOURCE_UNAVAILABLE',
            'SOURCE_STALE',
            'MAP_INVALIDATED',
            'MAP_COMPLETED',
            'SCOPE_RECENTLY_ADDED',
            'OBSERVATION_OVERDUE',
            'CURRENT_EVALUATION'
        )),
    CONSTRAINT chk_native_short_scope_status_v1_observation_freshness
        CHECK (observation_freshness_state IN ('OBSERVATION_CURRENT', 'OBSERVATION_OVERDUE', 'NO_OBSERVATION')),
    CONSTRAINT chk_native_short_scope_status_v1_source_freshness
        CHECK (source_freshness_state IN ('SOURCE_CURRENT', 'SOURCE_STALE', 'SOURCE_UNAVAILABLE')),
    CONSTRAINT chk_native_short_scope_status_v1_actionability
        CHECK (actionability_state IN (
            'ACTIONABLE_ACTIVE_MAP',
            'NO_ACTIONABLE_MAP',
            'TERMINAL_MAP',
            'BLOCKED_SOURCE',
            'BLOCKED_OBSERVATION',
            'BLOCKED_SCOPE'
        ))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Rebuildable current native SHORT scope-status projection. One row per SUPPORTED scope at projection_as_of_utc.';


CREATE TABLE IF NOT EXISTS native_short_scope_cadence_config_v1 (
    cadence_config_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL,
    fib_trading_horizon VARCHAR(32) NOT NULL,
    primary_interval    VARCHAR(16) NOT NULL,
    supporting_interval VARCHAR(16) NOT NULL,

    cadence_contract_version VARCHAR(32) NOT NULL,
    target_evaluation_interval VARCHAR(16) NOT NULL,
    primary_source_freshness_limit_seconds INT UNSIGNED NOT NULL,
    supporting_source_freshness_limit_seconds INT UNSIGNED NOT NULL,
    evaluation_grace_seconds INT UNSIGNED NOT NULL,
    recent_scope_grace_seconds INT UNSIGNED NOT NULL,
    effective_from_utc DATETIME(6) NOT NULL,
    effective_to_utc DATETIME(6) NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_native_short_scope_cadence_config_v1_scope_version (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval, cadence_contract_version
    ),
    KEY idx_native_short_scope_cadence_config_v1_scope_effective (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval, effective_from_utc
    ),
    KEY idx_native_short_scope_cadence_config_v1_active (is_active),

    CONSTRAINT chk_native_short_scope_cadence_config_v1_horizon
        CHECK (fib_trading_horizon = 'SHORT'),
    CONSTRAINT chk_native_short_scope_cadence_config_v1_primary
        CHECK (primary_interval = '4h'),
    CONSTRAINT chk_native_short_scope_cadence_config_v1_supporting
        CHECK (supporting_interval = '1h'),
    CONSTRAINT chk_native_short_scope_cadence_config_v1_target
        CHECK (target_evaluation_interval = '1h'),
    CONSTRAINT chk_native_short_scope_cadence_config_v1_active
        CHECK (is_active IN (0, 1)),
    CONSTRAINT chk_native_short_scope_cadence_config_v1_effective
        CHECK (effective_to_utc IS NULL OR effective_to_utc > effective_from_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Exact full-key native SHORT cadence/grace configuration. No wildcard inheritance in V1.';


CREATE TABLE IF NOT EXISTS native_short_scope_support_event_v1 (
    scope_support_event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL,
    fib_trading_horizon VARCHAR(32) NOT NULL,
    primary_interval    VARCHAR(16) NOT NULL,
    supporting_interval VARCHAR(16) NOT NULL,

    scope_support_state VARCHAR(32) NOT NULL COMMENT 'SUPPORTED | NOT_APPLICABLE',
    event_ts_utc DATETIME(6) NOT NULL,
    reason_code VARCHAR(64) NULL,
    reason_detail VARCHAR(255) NULL,
    source_name VARCHAR(96) NOT NULL,
    source_version VARCHAR(32) NOT NULL,
    event_metadata_json LONGTEXT NULL,
    created_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    KEY idx_native_short_scope_support_event_v1_scope_event (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval, event_ts_utc, scope_support_event_id
    ),
    KEY idx_native_short_scope_support_event_v1_scope_state_event (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval, scope_support_state, event_ts_utc
    ),

    CONSTRAINT chk_native_short_scope_support_event_v1_horizon
        CHECK (fib_trading_horizon = 'SHORT'),
    CONSTRAINT chk_native_short_scope_support_event_v1_state
        CHECK (scope_support_state IN ('SUPPORTED', 'NOT_APPLICABLE'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only native SHORT scope support-state history. Historical state before migration backfill is UNKNOWN_AT_AS_OF.';


SET @native_short_scope_support_backfill_ts_utc = UTC_TIMESTAMP(6);

INSERT INTO native_short_scope_support_event_v1 (
    venue,
    symbol,
    quote_currency,
    fib_trading_horizon,
    primary_interval,
    supporting_interval,
    scope_support_state,
    event_ts_utc,
    reason_code,
    reason_detail,
    source_name,
    source_version,
    event_metadata_json,
    created_at_utc
)
SELECT
    s.venue,
    s.symbol,
    s.quote_currency,
    s.fib_trading_horizon,
    s.primary_interval,
    s.supporting_interval,
    s.scope_support_state,
    @native_short_scope_support_backfill_ts_utc,
    'MIGRATION_BACKFILL',
    'Initial scope support event copied from current registry; pre-backfill history is UNKNOWN_AT_AS_OF',
    'native_short_scope_status_persistence_v1_migration',
    '20260706',
    JSON_OBJECT(
        'source_table', 'native_short_map_scope_v1',
        'backfill_rule', 'current_state_only',
        'pre_backfill_history', 'UNKNOWN_AT_AS_OF'
    ),
    @native_short_scope_support_backfill_ts_utc
FROM native_short_map_scope_v1 s
WHERE NOT EXISTS (
    SELECT 1
    FROM native_short_scope_support_event_v1 existing
    WHERE existing.venue               = s.venue
      AND existing.symbol              = s.symbol
      AND existing.quote_currency      = s.quote_currency
      AND existing.fib_trading_horizon = s.fib_trading_horizon
      AND existing.primary_interval    = s.primary_interval
      AND existing.supporting_interval = s.supporting_interval
      AND existing.source_name         = 'native_short_scope_status_persistence_v1_migration'
      AND existing.source_version      = '20260706'
);
