-- Migration: ffg_research_universe_v1
-- Boundary: research-only · market-only · account-agnostic
--           no is_enabled changes · no positions · no orders · no broker writes
--
-- Purpose: persistent storage for the FFG_RESEARCH_UNIVERSE_V1 external research universe.
--   Three tables:
--     1. ffg_research_universe_member_v1 — canonical membership (102 symbols, 2 excluded)
--     2. ffg_research_source_pair_v1    — source pairs preserving all exchange listings
--     3. ffg_external_signal_snapshot_v1 — idempotent source snapshots keyed by (source, captured_on, timeframe)
--
-- Safety:
--   account_plan_default enforced to NOT_ENABLED by CHECK constraint.
--   No foreign key on asset_id — FFG symbols are not required to exist in the asset table.
--   Signal snapshots keep source_confidence to prevent silent promotion.
--   Same-key corrected imports update the logical snapshot in place; different dates/timeframes preserve history.
--
-- Acceptance:
--   source rows: 109
--   canonical symbols: 102
--   research-universe members: 100
--   excluded: 2 (USDT, XPLUS)

-- ---------------------------------------------------------------------------
-- 1. ffg_research_universe_member_v1
-- One row per canonical (universe_key, source_symbol). Deduplicated.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ffg_research_universe_member_v1 (
    ffg_universe_member_id   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    universe_key    VARCHAR(64)  NOT NULL COMMENT 'e.g. FFG_RESEARCH_UNIVERSE_V1',
    source_symbol   VARCHAR(32)  NOT NULL COMMENT 'Canonical deduped source symbol',

    -- Nullable link to asset table; NULL when symbol is not yet in the asset table.
    -- Not enforced as FK because FFG symbols may not exist locally.
    asset_id        INT(11)      DEFAULT NULL COMMENT 'Matching asset.asset_id or NULL',

    source_name     VARCHAR(128) NOT NULL DEFAULT '' COMMENT 'Primary display name from FFG',
    ffg_virtual_portfolio_return_pct DECIMAL(10,4) DEFAULT NULL
        COMMENT 'FFG virtual $2000-per-token portfolio return. Source metadata only, not a Synth score.',

    research_status VARCHAR(32)  NOT NULL COMMENT 'RESEARCH_UNIVERSE | EXCLUDED',
    identity_status VARCHAR(64)  NOT NULL
        COMMENT 'source_pair_resolved | requires_identity_resolution | do_not_import',
    priority_tier   VARCHAR(32)  NOT NULL DEFAULT ''
        COMMENT 'rotation_core | theme_core | theme_watch | research_watch | broad_research | macro_benchmark',

    bitvavo_eur_resolution VARCHAR(64) NOT NULL DEFAULT 'PENDING_LOCAL_MARKET_SYNC'
        COMMENT 'RESOLVED | UNAVAILABLE_ON_BITVAVO | REQUIRES_MANUAL_RESOLUTION | PENDING_LOCAL_MARKET_SYNC',

    account_plan_default VARCHAR(32) NOT NULL DEFAULT 'NOT_ENABLED'
        COMMENT 'Always NOT_ENABLED — enforced by CHECK constraint below.',

    theme_tags      JSON         DEFAULT NULL COMMENT 'Array of theme tag strings from FFG.',
    exclusion_reason VARCHAR(128) DEFAULT NULL COMMENT 'Reason when research_status = EXCLUDED.',

    seed_schema_version VARCHAR(64) NOT NULL DEFAULT ''
        COMMENT 'schema_version from the seed JSON, e.g. ffg_research_universe_seed_v1',

    imported_at_utc  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at_utc   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                     ON UPDATE CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_ffg_universe_member (universe_key, source_symbol),
    KEY idx_ffg_universe_member_status (universe_key, research_status, bitvavo_eur_resolution),
    KEY idx_ffg_universe_member_asset (asset_id),
    KEY idx_ffg_universe_member_tier (universe_key, priority_tier),

    CONSTRAINT chk_ffg_universe_member_research_status
        CHECK (research_status IN ('RESEARCH_UNIVERSE', 'EXCLUDED')),
    CONSTRAINT chk_ffg_universe_member_account_plan
        CHECK (account_plan_default = 'NOT_ENABLED'),
    CONSTRAINT chk_ffg_universe_member_bitvavo_resolution
        CHECK (bitvavo_eur_resolution IN (
            'PENDING_LOCAL_MARKET_SYNC',
            'RESOLVED',
            'UNAVAILABLE_ON_BITVAVO',
            'REQUIRES_MANUAL_RESOLUTION'
        ))

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='FFG research universe canonical membership. Research-only. No account plan, no execution, no orders.';


-- ---------------------------------------------------------------------------
-- 2. ffg_research_source_pair_v1
-- One row per (universe_key, source_symbol, source_pair). 109 rows for V1.
-- Preserves all source exchange listings for provenance tracing.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ffg_research_source_pair_v1 (
    ffg_source_pair_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    universe_key    VARCHAR(64)  NOT NULL,
    source_symbol   VARCHAR(32)  NOT NULL,
    source_pair     VARCHAR(64)  NOT NULL COMMENT 'e.g. BINANCE:WLDUSDT',
    source_exchange VARCHAR(32)  NOT NULL COMMENT 'Exchange prefix from source_pair, e.g. BINANCE',

    created_at_utc DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_ffg_source_pair (universe_key, source_symbol, source_pair),
    KEY idx_ffg_source_pair_symbol (universe_key, source_symbol),
    KEY idx_ffg_source_pair_exchange (source_exchange)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='FFG source pairs per canonical symbol. Multiple rows when a symbol has listings on multiple exchanges.';


-- ---------------------------------------------------------------------------
-- 3. ffg_external_signal_snapshot_v1
-- One logical row per (source, captured_on, timeframe).
-- Stores beta flow inflow/outflow metadata as JSON.
-- source_confidence = low enforces no automatic gate effect.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ffg_external_signal_snapshot_v1 (
    ffg_signal_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    source           VARCHAR(64)  NOT NULL COMMENT 'e.g. FFG',
    captured_on      DATE         NOT NULL COMMENT 'Date the snapshot was captured',
    timeframe        VARCHAR(64)  NOT NULL COMMENT 'e.g. UNVERIFIED_BETA',
    source_confidence VARCHAR(32) NOT NULL DEFAULT 'low'
        COMMENT 'low | medium | high. Controls whether downstream logic may use this.',

    reported_inflow_count  INT NOT NULL DEFAULT 0,
    captured_inflow_count  INT NOT NULL DEFAULT 0,
    reported_outflow_count INT NOT NULL DEFAULT 0,

    inflows          JSON DEFAULT NULL
        COMMENT 'Captured inflow records: [{symbol, change_pct, reported_flow_usd, peak_flag}]',
    outflow_symbols  JSON DEFAULT NULL
        COMMENT 'Array of outflow symbol strings.',
    snapshot_notes   JSON DEFAULT NULL
        COMMENT 'Provider notes about this snapshot.',

    created_at_utc  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_ffg_signal_snapshot (source, captured_on, timeframe),
    KEY idx_ffg_signal_snapshot_date (captured_on, source),

    CONSTRAINT chk_ffg_signal_snapshot_confidence
        CHECK (source_confidence IN ('low', 'medium', 'high'))

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='FFG external research signal snapshots. Same-key corrected imports update in place; source_confidence=low prevents gate/score effects.';
