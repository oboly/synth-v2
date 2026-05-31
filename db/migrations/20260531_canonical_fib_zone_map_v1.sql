-- Migration: canonical_fib_zone_map_v1
-- Boundary: market-only · account-agnostic · dashboard/research source only
-- Purpose: canonical DB-backed source for fib/zone/target/invalidation/current-leg map context
-- Non-goals: no advice labels · no decision permission · no execution intent · no broker/order/account fields

CREATE TABLE IF NOT EXISTS canonical_fib_zone_map_v1 (
    map_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue           VARCHAR(32)  NOT NULL,
    symbol          VARCHAR(32)  NOT NULL,
    interval_code   VARCHAR(16)  NOT NULL,
    asof_ts_utc     DATETIME(6)  NOT NULL,
    map_version     VARCHAR(64)  NOT NULL DEFAULT 'canonical_fib_zone_map_v1',
    map_status      VARCHAR(32)  NOT NULL,
    map_quality     VARCHAR(32)  NOT NULL DEFAULT 'UNKNOWN',
    source_family   VARCHAR(64)  NOT NULL,
    source_ref      VARCHAR(255) NULL,
    source_created_at_utc DATETIME(6) NULL,

    -- Leg / direction
    current_leg     VARCHAR(16)  NOT NULL DEFAULT 'UNKNOWN',
    leg_method      VARCHAR(64)  NOT NULL,
    leg_confidence  VARCHAR(32)  NOT NULL DEFAULT 'UNKNOWN',

    -- Anchor / swing
    anchor_low_ts_utc   DATETIME(6)    NULL,
    anchor_low_price    DECIMAL(30,12) NULL,
    anchor_high_ts_utc  DATETIME(6)    NULL,
    anchor_high_price   DECIMAL(30,12) NULL,
    swing_range_abs     DECIMAL(30,12) NULL,
    anchor_move_pct     DECIMAL(18,8)  NULL,
    anchor_method       VARCHAR(64)    NOT NULL,
    anchor_quality      VARCHAR(32)    NOT NULL DEFAULT 'UNKNOWN',

    -- Entry Zone
    entry_zone_low          DECIMAL(30,12) NULL,
    entry_zone_high         DECIMAL(30,12) NULL,
    entry_zone_mid          DECIMAL(30,12) NULL,
    entry_zone_method       VARCHAR(64)    NOT NULL,
    entry_zone_source_field VARCHAR(128)   NULL,

    -- Support / reaction
    support_reaction_zone_low   DECIMAL(30,12) NULL,
    support_reaction_zone_high  DECIMAL(30,12) NULL,
    support_reaction_method     VARCHAR(64)    NOT NULL,

    -- Targets
    target_t1              DECIMAL(30,12) NULL,
    target_t2              DECIMAL(30,12) NULL,
    target_extension       DECIMAL(30,12) NULL,
    target_method          VARCHAR(64)    NOT NULL,
    target_source_field    VARCHAR(128)   NULL,

    -- Invalidation
    invalidation_level         DECIMAL(30,12) NULL,
    invalidation_method        VARCHAR(64)    NOT NULL,
    invalidation_source_field  VARCHAR(128)   NULL,

    -- Optional derived distances
    distance_entry_to_target_pct       DECIMAL(18,8) NULL,
    distance_entry_to_invalidation_pct DECIMAL(18,8) NULL,
    reward_risk_hint                   DECIMAL(18,8) NULL,

    -- Freshness / provenance
    input_latest_candle_ts_utc DATETIME(6) NULL,
    source_freshness_state     VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    provenance_payload         LONGTEXT    NULL,
    created_at_utc             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at_utc             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_canonical_fib_zone_map_v1 (
        venue, symbol, interval_code, asof_ts_utc, map_version
    ),

    INDEX idx_canonical_fib_zone_map_v1_asof   (venue, interval_code, asof_ts_utc),
    INDEX idx_canonical_fib_zone_map_v1_symbol (symbol, interval_code, asof_ts_utc),
    INDEX idx_canonical_fib_zone_map_v1_status (map_status, asof_ts_utc),
    INDEX idx_canonical_fib_zone_map_v1_leg    (current_leg, asof_ts_utc),
    INDEX idx_canonical_fib_zone_map_v1_source (source_family, asof_ts_utc)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Canonical market-only fib/zone strategy map source for dashboards and research. No advice, no account, no broker, no execution fields.';


CREATE OR REPLACE VIEW canonical_fib_zone_map_latest_v1 AS
SELECT m.*
FROM canonical_fib_zone_map_v1 m
JOIN (
    SELECT
        venue,
        symbol,
        interval_code,
        map_version,
        MAX(asof_ts_utc) AS max_asof_ts_utc
    FROM canonical_fib_zone_map_v1
    GROUP BY venue, symbol, interval_code, map_version
) latest
  ON latest.venue = m.venue
 AND latest.symbol = m.symbol
 AND latest.interval_code = m.interval_code
 AND latest.map_version = m.map_version
 AND latest.max_asof_ts_utc = m.asof_ts_utc;
