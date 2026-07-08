-- Migration: native_short_map_level_status_persistence_v1
-- Boundary: market-only rebuildable persistence only
-- Purpose:
--   1. Persist current per-level status rows for the projection-selected native SHORT map.
--   2. Preserve immutable analytical price and public tick-normalized evidence separately.
--   3. Keep per-level status tied to an explicit projection/evaluation clock.
-- Non-goals:
--   - no materializer runner integration
--   - no current-state evaluator
--   - no presentation-layer changes
--   - no order handling
--   - no deployment wiring

CREATE TABLE IF NOT EXISTS native_short_map_level_status_v1 (
    map_level_status_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL DEFAULT 'EUR',
    fib_trading_horizon VARCHAR(16) NOT NULL DEFAULT 'SHORT',
    primary_interval    VARCHAR(16) NOT NULL DEFAULT '4h',
    supporting_interval VARCHAR(16) NOT NULL DEFAULT '1h',

    current_map_id BIGINT UNSIGNED NOT NULL,
    map_cycle_id   VARCHAR(255) NOT NULL,

    canonical_map_level_role VARCHAR(32) NOT NULL COMMENT 'SELL_EXT_1_272 | SELL_EXT_1_618 | SELL_EXT_2_000',
    side                     VARCHAR(8)  NOT NULL COMMENT 'SELL',

    canonical_unrounded_price    DECIMAL(30,12) NOT NULL,
    canonical_tick_rounded_price DECIMAL(30,12) NULL,
    tick_rule_status             VARCHAR(64) NOT NULL COMMENT 'TICK_RULE_APPLIED | MISSING_TICK_RULE',
    tick_rule_source             VARCHAR(64) NOT NULL COMMENT 'TICK_RULE_FROM_DB | TICK_RULE_FROM_STATIC | MISSING_TICK_RULE',

    level_lifecycle_state VARCHAR(16) NOT NULL COMMENT 'ACTIVE | REACHED | PASSED | COMPLETED | HISTORICAL',
    level_status_as_of_utc DATETIME(6) NOT NULL,
    evaluation_reference   VARCHAR(32) NOT NULL COMMENT 'PRIMARY_4H_CLOSED_CANDLES | MAP_LIFECYCLE_EVENT',
    reason_code            VARCHAR(96) NOT NULL,

    projection_scope_status_code     VARCHAR(64) NOT NULL,
    projection_map_lifecycle_state   VARCHAR(64) NOT NULL,
    projection_actionability_state   VARCHAR(64) NOT NULL,

    rebuilt_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_native_short_map_level_status_v1_identity (
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        current_map_id,
        canonical_map_level_role,
        side,
        canonical_unrounded_price
    ),
    KEY idx_native_short_map_level_status_v1_scope_asof (
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        level_status_as_of_utc
    ),
    KEY idx_native_short_map_level_status_v1_map (
        current_map_id,
        canonical_map_level_role,
        level_lifecycle_state
    ),
    KEY idx_native_short_map_level_status_v1_lifecycle (
        level_lifecycle_state,
        level_status_as_of_utc
    ),
    KEY idx_native_short_map_level_status_v1_projection_status (
        projection_scope_status_code,
        projection_map_lifecycle_state,
        projection_actionability_state
    ),

    CONSTRAINT fk_native_short_map_level_status_v1_map_scope
        FOREIGN KEY (
            current_map_id,
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
    CONSTRAINT chk_native_short_map_level_status_v1_price_positive
        CHECK (canonical_unrounded_price > 0),
    CONSTRAINT chk_native_short_map_level_status_v1_tick_price_positive
        CHECK (canonical_tick_rounded_price IS NULL OR canonical_tick_rounded_price > 0),
    CONSTRAINT chk_native_short_map_level_status_v1_tick_rule
        CHECK (
            (
                tick_rule_status = 'MISSING_TICK_RULE'
                AND tick_rule_source = 'MISSING_TICK_RULE'
                AND canonical_tick_rounded_price IS NULL
            )
            OR
            (
                tick_rule_status = 'TICK_RULE_APPLIED'
                AND tick_rule_source IN ('TICK_RULE_FROM_DB', 'TICK_RULE_FROM_STATIC')
                AND canonical_tick_rounded_price IS NOT NULL
            )
        ),
    CONSTRAINT chk_native_short_map_level_status_v1_lifecycle
        CHECK (level_lifecycle_state IN ('ACTIVE', 'REACHED', 'PASSED', 'COMPLETED', 'HISTORICAL')),
    CONSTRAINT chk_native_short_map_level_status_v1_evaluation_reference
        CHECK (evaluation_reference IN ('PRIMARY_4H_CLOSED_CANDLES', 'MAP_LIFECYCLE_EVENT')),
    CONSTRAINT chk_native_short_map_level_status_v1_dynamic_gate
        CHECK (
            level_lifecycle_state NOT IN ('ACTIVE', 'REACHED', 'PASSED')
            OR
            (
                evaluation_reference = 'PRIMARY_4H_CLOSED_CANDLES'
                AND projection_scope_status_code = 'CURRENT_EVALUATION'
                AND projection_map_lifecycle_state = 'MAP_ACTIVE'
                AND projection_actionability_state = 'ACTIONABLE_ACTIVE_MAP'
            )
        ),
    CONSTRAINT chk_native_short_map_level_status_v1_dynamic_reason
        CHECK (
            (level_lifecycle_state <> 'ACTIVE' OR reason_code = 'NO_PRIMARY_HIGH_REACHED_LEVEL')
            AND
            (level_lifecycle_state <> 'REACHED' OR reason_code = 'PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE')
            AND
            (level_lifecycle_state <> 'PASSED' OR reason_code = 'PRIMARY_CLOSE_PASSED_LEVEL')
        ),
    CONSTRAINT chk_native_short_map_level_status_v1_completed_gate
        CHECK (
            level_lifecycle_state <> 'COMPLETED'
            OR
            (
                evaluation_reference = 'MAP_LIFECYCLE_EVENT'
                AND projection_map_lifecycle_state = 'MAP_COMPLETED'
                AND reason_code = 'MAP_COMPLETED'
            )
        ),
    CONSTRAINT chk_native_short_map_level_status_v1_historical_gate
        CHECK (
            level_lifecycle_state <> 'HISTORICAL'
            OR
            (
                evaluation_reference = 'MAP_LIFECYCLE_EVENT'
                AND (
                    (projection_map_lifecycle_state = 'MAP_INVALIDATED' AND reason_code = 'MAP_INVALIDATED')
                    OR
                    (projection_map_lifecycle_state = 'MAP_EXPIRED' AND reason_code = 'MAP_EXPIRED')
                )
            )
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Rebuildable current native SHORT map-level status rows for projection-selected SELL extension levels.';
