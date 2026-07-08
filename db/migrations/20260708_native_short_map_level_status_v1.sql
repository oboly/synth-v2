-- Migration: native_short_map_level_status_v1
-- Boundary: market-only persistent current read model only
-- Purpose:
--   Persist rebuildable per-level status rows for the projection-selected
--   native SHORT current map.
-- Non-goals:
--   - no materializer runner integration
--   - no candle lifecycle evaluation logic
--   - no reporting/UI consumer
--   - no account/order coverage
--   - no broker calls or writes
--   - no decision/execution/selection changes
--   - no scheduler, timer, service, wrapper, or deployment wiring

CREATE TABLE IF NOT EXISTS native_short_map_level_status_v1 (
    map_level_status_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL,
    fib_trading_horizon VARCHAR(32) NOT NULL,
    primary_interval    VARCHAR(16) NOT NULL,
    supporting_interval VARCHAR(16) NOT NULL,

    current_map_id BIGINT UNSIGNED NOT NULL,
    map_cycle_id   VARCHAR(255) NOT NULL,

    canonical_map_level_role VARCHAR(32) NOT NULL,
    side                     VARCHAR(8) NOT NULL,

    canonical_unrounded_price    DECIMAL(38, 18) NOT NULL,
    canonical_tick_rounded_price DECIMAL(38, 18) NULL,
    tick_rule_status             VARCHAR(64) NOT NULL,
    tick_rule_source             VARCHAR(64) NOT NULL,

    level_lifecycle_state  VARCHAR(32) NOT NULL,
    level_status_as_of_utc DATETIME(6) NOT NULL,
    evaluation_reference   VARCHAR(64) NOT NULL,
    reason_code            VARCHAR(96) NOT NULL,

    projection_scope_status_code    VARCHAR(64) NOT NULL,
    projection_map_lifecycle_state  VARCHAR(64) NOT NULL,
    projection_actionability_state  VARCHAR(64) NOT NULL,

    rebuilt_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_native_short_map_level_status_v1_identity (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
        current_map_id, canonical_map_level_role, side, canonical_unrounded_price
    ),
    KEY idx_native_short_map_level_status_v1_scope (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval
    ),
    KEY idx_native_short_map_level_status_v1_map (current_map_id),
    KEY idx_native_short_map_level_status_v1_cycle (map_cycle_id),
    KEY idx_native_short_map_level_status_v1_state (level_lifecycle_state),
    KEY idx_native_short_map_level_status_v1_as_of (level_status_as_of_utc),

    CONSTRAINT fk_native_short_map_level_status_v1_map
        FOREIGN KEY (current_map_id) REFERENCES native_short_map_v1 (map_id),

    CONSTRAINT chk_native_short_map_level_status_v1_horizon
        CHECK (fib_trading_horizon = 'SHORT'),
    CONSTRAINT chk_native_short_map_level_status_v1_primary
        CHECK (primary_interval = '4h'),
    CONSTRAINT chk_native_short_map_level_status_v1_supporting
        CHECK (supporting_interval = '1h'),
    CONSTRAINT chk_native_short_map_level_status_v1_role
        CHECK (canonical_map_level_role IN ('SELL_EXT_1_272', 'SELL_EXT_1_618', 'SELL_EXT_2_000')),
    CONSTRAINT chk_native_short_map_level_status_v1_side
        CHECK (side = 'SELL'),
    CONSTRAINT chk_native_short_map_level_status_v1_unrounded_positive
        CHECK (canonical_unrounded_price > 0),
    CONSTRAINT chk_native_short_map_level_status_v1_tick_positive
        CHECK (canonical_tick_rounded_price IS NULL OR canonical_tick_rounded_price > 0),
    CONSTRAINT chk_native_short_map_level_status_v1_tick_status
        CHECK (tick_rule_status IN ('TICK_RULE_APPLIED', 'MISSING_TICK_RULE')),
    CONSTRAINT chk_native_short_map_level_status_v1_tick_source
        CHECK (tick_rule_source IN ('TICK_RULE_FROM_DB', 'TICK_RULE_FROM_STATIC', 'MISSING_TICK_RULE')),
    CONSTRAINT chk_native_short_map_level_status_v1_tick_missing_null
        CHECK (
            (tick_rule_status = 'MISSING_TICK_RULE'
                AND tick_rule_source = 'MISSING_TICK_RULE'
                AND canonical_tick_rounded_price IS NULL)
            OR
            (tick_rule_status = 'TICK_RULE_APPLIED'
                AND tick_rule_source IN ('TICK_RULE_FROM_DB', 'TICK_RULE_FROM_STATIC')
                AND canonical_tick_rounded_price IS NOT NULL)
        ),
    CONSTRAINT chk_native_short_map_level_status_v1_lifecycle
        CHECK (level_lifecycle_state IN ('ACTIVE', 'REACHED', 'PASSED', 'COMPLETED', 'HISTORICAL')),
    CONSTRAINT chk_native_short_map_level_status_v1_eval_ref
        CHECK (evaluation_reference IN ('PRIMARY_4H_CLOSED_CANDLES', 'MAP_LIFECYCLE_EVENT')),
    CONSTRAINT chk_native_short_map_level_status_v1_reason
        CHECK (reason_code IN (
            'NO_PRIMARY_HIGH_REACHED_LEVEL',
            'PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE',
            'PRIMARY_CLOSE_PASSED_LEVEL',
            'MAP_COMPLETED',
            'MAP_INVALIDATED',
            'MAP_EXPIRED'
        )),
    CONSTRAINT chk_native_short_map_level_status_v1_projection_code
        CHECK (projection_scope_status_code IN (
            'CONFIGURATION_UNAVAILABLE',
            'SOURCE_UNAVAILABLE',
            'SOURCE_STALE',
            'MAP_INVALIDATED',
            'MAP_COMPLETED',
            'SCOPE_RECENTLY_ADDED',
            'OBSERVATION_OVERDUE',
            'CURRENT_EVALUATION'
        )),
    CONSTRAINT chk_native_short_map_level_status_v1_projection_lifecycle
        CHECK (projection_map_lifecycle_state IN (
            'MAP_ACTIVE',
            'MAP_INVALIDATED',
            'MAP_COMPLETED',
            'MAP_EXPIRED',
            'NO_CURRENT_MAP'
        )),
    CONSTRAINT chk_native_short_map_level_status_v1_projection_actionability
        CHECK (projection_actionability_state IN (
            'BLOCKED_CONFIGURATION',
            'ACTIONABLE_ACTIVE_MAP',
            'NO_ACTIONABLE_MAP',
            'TERMINAL_MAP',
            'BLOCKED_SOURCE',
            'BLOCKED_OBSERVATION',
            'BLOCKED_SCOPE'
        ))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Rebuildable current native SHORT per-map-level status projection. One collection per projection-selected current map.';
