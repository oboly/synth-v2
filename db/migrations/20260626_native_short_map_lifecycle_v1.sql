-- Migration: native_short_map_lifecycle_v1
-- Boundary: market-only · account-agnostic · no generator/runtime integration
-- Purpose:
--   1. Preserve immutable published native SHORT maps.
--   2. Preserve append-only generation attempts separately from lifecycle events.
--   3. Project current lifecycle state with explicit rebuild, failure, and unsupported scope states.
-- Non-goals:
--   - no scheduler
--   - no UI/API wiring
--   - no wallet/account state
--   - no zone-engine / decision_gate / execution_planner / executor changes

CREATE TABLE IF NOT EXISTS native_short_map_scope_v1 (
    scope_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL DEFAULT 'EUR',
    fib_trading_horizon VARCHAR(16) NOT NULL DEFAULT 'SHORT',
    primary_interval    VARCHAR(16) NOT NULL DEFAULT '4h',
    supporting_interval VARCHAR(16) NOT NULL DEFAULT '1h',

    scope_support_state VARCHAR(32) NOT NULL COMMENT 'SUPPORTED | NOT_APPLICABLE',
    scope_reason_code   VARCHAR(64) NULL,
    scope_reason_detail VARCHAR(255) NULL,

    created_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_native_short_map_scope_v1_scope (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval
    ),
    KEY idx_native_short_map_scope_v1_support (
        scope_support_state, venue, symbol, quote_currency, primary_interval
    ),

    CONSTRAINT chk_native_short_map_scope_v1_horizon
        CHECK (fib_trading_horizon = 'SHORT'),
    CONSTRAINT chk_native_short_map_scope_v1_support
        CHECK (scope_support_state IN ('SUPPORTED', 'NOT_APPLICABLE'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Current market-only scope registry for native SHORT map lifecycle projection.';


CREATE TABLE IF NOT EXISTS native_short_map_v1 (
    map_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL DEFAULT 'EUR',
    fib_trading_horizon VARCHAR(16) NOT NULL DEFAULT 'SHORT',
    primary_interval    VARCHAR(16) NOT NULL DEFAULT '4h',
    supporting_interval VARCHAR(16) NOT NULL DEFAULT '1h',

    map_schema_version               VARCHAR(64) NOT NULL DEFAULT 'native_short_map_v1',
    generator_name                   VARCHAR(64) NOT NULL,
    generator_version                VARCHAR(64) NOT NULL,
    fib_model_name                   VARCHAR(64) NOT NULL,
    fib_model_version                VARCHAR(64) NOT NULL,
    structure_hash                   CHAR(64) NOT NULL COMMENT 'Stable content hash for material structure identity',
    published_generation_attempt_id  VARCHAR(64) NOT NULL,
    market_snapshot_ts_utc           DATETIME(6) NULL COMMENT 'Publication metadata only; not part of immutable definition identity',
    published_at_utc                 DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    map_cycle_id          VARCHAR(128) NULL,
    previous_map_id       BIGINT UNSIGNED NULL,
    previous_map_cycle_id VARCHAR(128) NULL,

    anchor_low_ts_utc     DATETIME(6)    NULL,
    anchor_low_price      DECIMAL(30,12) NULL,
    anchor_high_ts_utc    DATETIME(6)    NULL,
    anchor_high_price     DECIMAL(30,12) NULL,
    retrace_ratio         DECIMAL(18,8)  NULL,
    retrace_price         DECIMAL(30,12) NULL,
    fib_ratios_json       LONGTEXT       NOT NULL,
    target_levels_json    LONGTEXT       NOT NULL,
    invalidation_price    DECIMAL(30,12) NULL,
    invalidation_rule     VARCHAR(128)   NOT NULL DEFAULT '',

    source_primary_candle_ts_utc   DATETIME(6) NULL,
    source_support_candle_ts_utc   DATETIME(6) NULL,
    source_primary_ref             VARCHAR(255) NOT NULL DEFAULT '',
    source_support_ref             VARCHAR(255) NOT NULL DEFAULT '',
    source_primary_candle_count    INT NOT NULL DEFAULT 0,
    source_support_candle_count    INT NOT NULL DEFAULT 0,

    map_payload_json LONGTEXT NOT NULL COMMENT 'Canonical immutable full payload',
    created_at_utc   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_native_short_map_v1_definition (
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        generator_name,
        generator_version,
        structure_hash
    ),
    UNIQUE KEY uq_native_short_map_v1_map_scope (
        map_id,
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval
    ),
    KEY idx_native_short_map_v1_scope_publish (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval, published_at_utc, map_id
    ),
    KEY idx_native_short_map_v1_structure (structure_hash),
    KEY idx_native_short_map_v1_previous_map_scope (
        previous_map_id,
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval
    ),

    CONSTRAINT fk_native_short_map_v1_previous_map_scope
        FOREIGN KEY (
            previous_map_id,
            venue,
            symbol,
            quote_currency,
            fib_trading_horizon,
            primary_interval,
            supporting_interval
        )
        REFERENCES native_short_map_v1 (
            map_id,
            venue,
            symbol,
            quote_currency,
            fib_trading_horizon,
            primary_interval,
            supporting_interval
        ),
    CONSTRAINT chk_native_short_map_v1_horizon
        CHECK (fib_trading_horizon = 'SHORT')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Immutable published native SHORT maps with first-class provenance and queryable map definition fields.';


CREATE TABLE IF NOT EXISTS native_short_map_generation_event_v1 (
    generation_event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL DEFAULT 'EUR',
    fib_trading_horizon VARCHAR(16) NOT NULL DEFAULT 'SHORT',
    primary_interval    VARCHAR(16) NOT NULL DEFAULT '4h',
    supporting_interval VARCHAR(16) NOT NULL DEFAULT '1h',

    generation_attempt_id VARCHAR(64) NOT NULL,
    event_type            VARCHAR(32) NOT NULL COMMENT 'ATTEMPT_STARTED | PUBLISHED | REJECTED | SKIPPED | FAILED',
    event_ts_utc          DATETIME(6) NOT NULL,
    reason_code           VARCHAR(64) NULL,
    reason_detail         VARCHAR(255) NULL,
    trigger_type          VARCHAR(64) NULL,
    candidate_map_cycle_id             VARCHAR(128) NULL,
    candidate_previous_map_id          BIGINT UNSIGNED NULL,
    candidate_primary_lifecycle_state  VARCHAR(64) NULL,
    candidate_current_map_status       VARCHAR(64) NULL,
    latest_primary_close_ts_utc        DATETIME(6) NULL,
    latest_support_close_ts_utc        DATETIME(6) NULL,
    latest_primary_close_price         DECIMAL(30,12) NULL,
    source_primary_ref                 VARCHAR(255) NULL,
    source_support_ref                 VARCHAR(255) NULL,
    source_primary_candle_count        INT NULL,
    source_support_candle_count        INT NULL,
    map_id                BIGINT UNSIGNED NULL,
    event_metadata_json   LONGTEXT NULL,

    terminal_attempt_guard VARCHAR(255)
        GENERATED ALWAYS AS (
            CASE
                WHEN event_type IN ('PUBLISHED', 'REJECTED', 'SKIPPED', 'FAILED')
                THEN CONCAT(
                    venue, '|', symbol, '|', quote_currency, '|', fib_trading_horizon, '|',
                    primary_interval, '|', supporting_interval, '|', generation_attempt_id
                )
                ELSE NULL
            END
        ) STORED,

    created_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_native_short_map_generation_event_v1_attempt_event (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval, generation_attempt_id, event_type
    ),
    UNIQUE KEY uq_native_short_map_generation_event_v1_terminal_guard (terminal_attempt_guard),
    KEY idx_native_short_map_generation_event_v1_scope_id (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval, generation_event_id
    ),
    KEY idx_native_short_map_generation_event_v1_map_scope (
        map_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval
    ),

    CONSTRAINT fk_native_short_map_generation_event_v1_map_scope
        FOREIGN KEY (
            map_id,
            venue,
            symbol,
            quote_currency,
            fib_trading_horizon,
            primary_interval,
            supporting_interval
        ) REFERENCES native_short_map_v1 (
            map_id,
            venue,
            symbol,
            quote_currency,
            fib_trading_horizon,
            primary_interval,
            supporting_interval
        ),
    CONSTRAINT chk_native_short_map_generation_event_v1_horizon
        CHECK (fib_trading_horizon = 'SHORT'),
    CONSTRAINT chk_native_short_map_generation_event_v1_type
        CHECK (event_type IN ('ATTEMPT_STARTED', 'PUBLISHED', 'REJECTED', 'SKIPPED', 'FAILED')),
    CONSTRAINT chk_native_short_map_generation_event_v1_publish_map
        CHECK (
            (event_type = 'PUBLISHED' AND map_id IS NOT NULL)
            OR
            (event_type <> 'PUBLISHED' AND map_id IS NULL)
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only generation attempt ledger for native SHORT maps. PUBLISHED rows must reference a map in the identical market scope.';


CREATE TABLE IF NOT EXISTS native_short_map_lifecycle_event_v1 (
    lifecycle_event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    map_id               BIGINT UNSIGNED NOT NULL,
    lifecycle_event_type VARCHAR(32) NOT NULL COMMENT 'ACTIVATED | COMPLETED | EXPIRED | INVALIDATED | SUPERSEDED',
    successor_map_id     BIGINT UNSIGNED NULL,
    event_ts_utc         DATETIME(6) NOT NULL,
    reason_code          VARCHAR(64) NULL,
    reason_detail        VARCHAR(255) NULL,
    observed_current_price         DECIMAL(30,12) NULL,
    observed_max_high_since_anchor DECIMAL(30,12) NULL,
    observed_min_low_since_anchor  DECIMAL(30,12) NULL,
    latest_primary_close_ts_utc    DATETIME(6) NULL,
    latest_support_close_ts_utc    DATETIME(6) NULL,
    observer_name                  VARCHAR(64) NULL,
    observer_version               VARCHAR(64) NULL,
    event_metadata_json  LONGTEXT NULL,

    terminal_map_guard BIGINT UNSIGNED
        GENERATED ALWAYS AS (
            CASE
                WHEN lifecycle_event_type IN ('COMPLETED', 'EXPIRED', 'INVALIDATED', 'SUPERSEDED')
                THEN map_id
                ELSE NULL
            END
        ) STORED,

    created_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_native_short_map_lifecycle_event_v1_map_type (map_id, lifecycle_event_type),
    UNIQUE KEY uq_native_short_map_lifecycle_event_v1_terminal_guard (terminal_map_guard),
    KEY idx_native_short_map_lifecycle_event_v1_map_id (map_id, lifecycle_event_id),
    KEY idx_native_short_map_lifecycle_event_v1_successor (successor_map_id),

    CONSTRAINT fk_native_short_map_lifecycle_event_v1_map
        FOREIGN KEY (map_id) REFERENCES native_short_map_v1 (map_id),
    CONSTRAINT fk_native_short_map_lifecycle_event_v1_successor_map
        FOREIGN KEY (successor_map_id) REFERENCES native_short_map_v1 (map_id),
    CONSTRAINT chk_native_short_map_lifecycle_event_v1_type
        CHECK (lifecycle_event_type IN ('ACTIVATED', 'COMPLETED', 'EXPIRED', 'INVALIDATED', 'SUPERSEDED')),
    CONSTRAINT chk_native_short_map_lifecycle_event_v1_successor
        CHECK (
            (lifecycle_event_type = 'SUPERSEDED' AND successor_map_id IS NOT NULL)
            OR
            (lifecycle_event_type <> 'SUPERSEDED')
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only lifecycle ledger for published native SHORT maps. Terminal outcome is exclusive per map.';


CREATE OR REPLACE VIEW native_short_map_latest_lifecycle_event_v1 AS
SELECT e.*
FROM native_short_map_lifecycle_event_v1 e
JOIN (
    SELECT
        map_id,
        MAX(lifecycle_event_id) AS max_lifecycle_event_id
    FROM native_short_map_lifecycle_event_v1
    GROUP BY map_id
) latest
  ON latest.max_lifecycle_event_id = e.lifecycle_event_id;


CREATE OR REPLACE VIEW native_short_map_latest_active_v1 AS
SELECT
    m.map_id,
    m.venue,
    m.symbol,
    m.quote_currency,
    m.fib_trading_horizon,
    m.primary_interval,
    m.supporting_interval,
    m.structure_hash,
    m.generator_name,
    m.generator_version,
    m.fib_model_name,
    m.fib_model_version,
    m.market_snapshot_ts_utc,
    m.published_at_utc,
    le.lifecycle_event_type AS latest_lifecycle_event_type,
    le.event_ts_utc AS latest_lifecycle_event_ts_utc
FROM native_short_map_v1 m
LEFT JOIN native_short_map_latest_lifecycle_event_v1 le
  ON le.map_id = m.map_id
WHERE (le.map_id IS NULL OR le.lifecycle_event_type = 'ACTIVATED')
  AND NOT EXISTS (
      SELECT 1
      FROM native_short_map_v1 other_m
      LEFT JOIN native_short_map_latest_lifecycle_event_v1 other_le
        ON other_le.map_id = other_m.map_id
      WHERE other_m.venue               = m.venue
        AND other_m.symbol              = m.symbol
        AND other_m.quote_currency      = m.quote_currency
        AND other_m.fib_trading_horizon = m.fib_trading_horizon
        AND other_m.primary_interval    = m.primary_interval
        AND other_m.supporting_interval = m.supporting_interval
        AND (other_le.map_id IS NULL OR other_le.lifecycle_event_type = 'ACTIVATED')
        AND (
            other_m.published_at_utc > m.published_at_utc
            OR (
                other_m.published_at_utc = m.published_at_utc
                AND other_m.map_id > m.map_id
            )
        )
  );


CREATE OR REPLACE VIEW native_short_map_latest_terminal_v1 AS
SELECT candidate.*
FROM (
    SELECT
        m.map_id,
        m.venue,
        m.symbol,
        m.quote_currency,
        m.fib_trading_horizon,
        m.primary_interval,
        m.supporting_interval,
        le.lifecycle_event_id,
        le.lifecycle_event_type,
        le.event_ts_utc,
        le.reason_code
    FROM native_short_map_v1 m
    JOIN native_short_map_latest_lifecycle_event_v1 le
      ON le.map_id = m.map_id
    WHERE le.lifecycle_event_type IN ('COMPLETED', 'EXPIRED', 'INVALIDATED', 'SUPERSEDED')
) candidate
JOIN (
    SELECT
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        MAX(lifecycle_event_id) AS max_lifecycle_event_id
    FROM (
        SELECT
            m.venue,
            m.symbol,
            m.quote_currency,
            m.fib_trading_horizon,
            m.primary_interval,
            m.supporting_interval,
            le.lifecycle_event_id
        FROM native_short_map_v1 m
        JOIN native_short_map_latest_lifecycle_event_v1 le
          ON le.map_id = m.map_id
        WHERE le.lifecycle_event_type IN ('COMPLETED', 'EXPIRED', 'INVALIDATED', 'SUPERSEDED')
    ) terminal_scope
    GROUP BY venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval
) latest
  ON latest.max_lifecycle_event_id = candidate.lifecycle_event_id;


CREATE OR REPLACE VIEW native_short_map_open_attempt_v1 AS
SELECT started.*
FROM native_short_map_generation_event_v1 started
LEFT JOIN native_short_map_generation_event_v1 terminal
  ON terminal.venue                 = started.venue
 AND terminal.symbol                = started.symbol
 AND terminal.quote_currency        = started.quote_currency
 AND terminal.fib_trading_horizon   = started.fib_trading_horizon
 AND terminal.primary_interval      = started.primary_interval
 AND terminal.supporting_interval   = started.supporting_interval
 AND terminal.generation_attempt_id = started.generation_attempt_id
 AND terminal.event_type IN ('PUBLISHED', 'REJECTED', 'SKIPPED', 'FAILED')
WHERE started.event_type = 'ATTEMPT_STARTED'
  AND terminal.generation_event_id IS NULL;


CREATE OR REPLACE VIEW native_short_map_latest_open_attempt_v1 AS
SELECT candidate.*
FROM native_short_map_open_attempt_v1 candidate
JOIN (
    SELECT
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        MAX(generation_event_id) AS max_generation_event_id
    FROM native_short_map_open_attempt_v1
    GROUP BY venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval
) latest
  ON latest.max_generation_event_id = candidate.generation_event_id;


CREATE OR REPLACE VIEW native_short_map_latest_authoritative_generation_v1 AS
SELECT candidate.*
FROM native_short_map_generation_event_v1 candidate
JOIN (
    SELECT
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        MAX(generation_event_id) AS max_generation_event_id
    FROM native_short_map_generation_event_v1
    WHERE event_type IN ('PUBLISHED', 'REJECTED', 'FAILED')
    GROUP BY venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval
) latest
  ON latest.max_generation_event_id = candidate.generation_event_id;


CREATE OR REPLACE VIEW native_short_map_latest_skip_generation_v1 AS
SELECT candidate.*
FROM native_short_map_generation_event_v1 candidate
JOIN (
    SELECT
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        MAX(generation_event_id) AS max_generation_event_id
    FROM native_short_map_generation_event_v1
    WHERE event_type = 'SKIPPED'
    GROUP BY venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval
) latest
  ON latest.max_generation_event_id = candidate.generation_event_id;


CREATE OR REPLACE VIEW native_short_map_current_lifecycle_v1 AS
SELECT
    s.scope_id,
    s.venue,
    s.symbol,
    s.quote_currency,
    s.fib_trading_horizon,
    s.primary_interval,
    s.supporting_interval,
    s.scope_support_state,
    s.scope_reason_code,
    s.scope_reason_detail,

    CASE
        WHEN active_map.map_id IS NOT NULL THEN 'MAP_ACTIVE'
        WHEN open_attempt.generation_event_id IS NOT NULL THEN 'MAP_GENERATING'
        WHEN authoritative_generation.event_type = 'FAILED' THEN 'MAP_GENERATION_FAILED'
        WHEN authoritative_generation.event_type = 'REJECTED'
             AND authoritative_generation.reason_code IN (
                 'CANDLES_INSUFFICIENT',
                 'CANDLE_GAPS_DETECTED',
                 'CANDLE_SNAPSHOT_STALE',
                 'ASSET_HISTORY_TOO_SHORT',
                 'INGEST_LOOKBACK_LIMIT',
                 'NO_CLOSED_DAILY_CANDLES'
             ) THEN 'MAP_DATA_UNAVAILABLE'
        WHEN authoritative_generation.event_type = 'REJECTED' THEN 'MAP_REBUILD_REJECTED'
        WHEN terminal_map.map_id IS NOT NULL THEN 'MAP_REBUILD_REQUIRED'
        WHEN s.scope_support_state = 'SUPPORTED'
             AND active_map.map_id IS NULL
             AND open_attempt.generation_event_id IS NULL
             AND authoritative_generation.generation_event_id IS NULL
             AND terminal_map.map_id IS NULL THEN 'MAP_REBUILD_REQUIRED'
        WHEN s.scope_support_state = 'NOT_APPLICABLE' THEN 'MAP_NOT_APPLICABLE'
        ELSE 'MAP_REBUILD_REQUIRED'
    END AS lifecycle_state,

    CASE
        WHEN active_map.map_id IS NOT NULL THEN 'LATEST_ACTIVE_MAP'
        WHEN open_attempt.generation_event_id IS NOT NULL THEN 'OPEN_ATTEMPT'
        WHEN authoritative_generation.event_type IN ('FAILED', 'REJECTED') THEN authoritative_generation.event_type
        WHEN terminal_map.map_id IS NOT NULL THEN 'TERMINAL_MAP'
        WHEN s.scope_support_state = 'NOT_APPLICABLE' THEN 'SCOPE_POLICY'
        ELSE 'NO_AUTHORITATIVE_ATTEMPT'
    END AS lifecycle_state_source,

    active_map.map_id AS active_map_id,
    active_map.structure_hash AS active_map_structure_hash,
    active_map.published_at_utc AS active_map_published_at_utc,
    active_map.market_snapshot_ts_utc AS active_map_market_snapshot_ts_utc,

    open_attempt.generation_attempt_id AS open_generation_attempt_id,
    open_attempt.event_ts_utc AS open_generation_started_at_utc,

    authoritative_generation.generation_attempt_id AS latest_authoritative_attempt_id,
    authoritative_generation.event_type AS latest_authoritative_event_type,
    authoritative_generation.event_ts_utc AS latest_authoritative_event_ts_utc,
    authoritative_generation.reason_code AS latest_authoritative_reason_code,

    terminal_map.map_id AS latest_terminal_map_id,
    terminal_map.lifecycle_event_type AS latest_terminal_lifecycle_event_type,
    terminal_map.event_ts_utc AS latest_terminal_lifecycle_event_ts_utc,
    terminal_map.reason_code AS latest_terminal_reason_code,

    skipped_generation.generation_attempt_id AS latest_skip_attempt_id,
    skipped_generation.event_ts_utc AS latest_skip_event_ts_utc,
    skipped_generation.reason_code AS latest_skip_reason_code
FROM native_short_map_scope_v1 s
LEFT JOIN native_short_map_latest_active_v1 active_map
  ON active_map.venue               = s.venue
 AND active_map.symbol              = s.symbol
 AND active_map.quote_currency      = s.quote_currency
 AND active_map.fib_trading_horizon = s.fib_trading_horizon
 AND active_map.primary_interval    = s.primary_interval
 AND active_map.supporting_interval = s.supporting_interval
LEFT JOIN native_short_map_latest_open_attempt_v1 open_attempt
  ON open_attempt.venue                 = s.venue
 AND open_attempt.symbol                = s.symbol
 AND open_attempt.quote_currency        = s.quote_currency
 AND open_attempt.fib_trading_horizon   = s.fib_trading_horizon
 AND open_attempt.primary_interval      = s.primary_interval
 AND open_attempt.supporting_interval   = s.supporting_interval
LEFT JOIN native_short_map_latest_authoritative_generation_v1 authoritative_generation
  ON authoritative_generation.venue               = s.venue
 AND authoritative_generation.symbol              = s.symbol
 AND authoritative_generation.quote_currency      = s.quote_currency
 AND authoritative_generation.fib_trading_horizon = s.fib_trading_horizon
 AND authoritative_generation.primary_interval    = s.primary_interval
 AND authoritative_generation.supporting_interval = s.supporting_interval
LEFT JOIN native_short_map_latest_terminal_v1 terminal_map
  ON terminal_map.venue               = s.venue
 AND terminal_map.symbol              = s.symbol
 AND terminal_map.quote_currency      = s.quote_currency
 AND terminal_map.fib_trading_horizon = s.fib_trading_horizon
 AND terminal_map.primary_interval    = s.primary_interval
 AND terminal_map.supporting_interval = s.supporting_interval
LEFT JOIN native_short_map_latest_skip_generation_v1 skipped_generation
  ON skipped_generation.venue               = s.venue
 AND skipped_generation.symbol              = s.symbol
 AND skipped_generation.quote_currency      = s.quote_currency
 AND skipped_generation.fib_trading_horizon = s.fib_trading_horizon
 AND skipped_generation.primary_interval    = s.primary_interval
 AND skipped_generation.supporting_interval = s.supporting_interval;
