-- Migration: multi_account_asset_foundation_v1
-- Boundary: additive only · no asset column drops · no data migration · no broker/order fields
-- Purpose: create venue_market and account_asset tables to separate global asset identity
--          from venue-specific market metadata and per-account asset settings.
-- Non-goals: no ALTER TABLE asset · no is_tradeable/quote_asset column drops (Phase 2-4)
--            no decision_gate · no execution_planner · no executor · no broker calls

-- ---------------------------------------------------------------------------
-- venue_market
-- One row per (venue, market). Stores venue-specific market metadata.
-- Backfill: INSERT-SELECT from asset (symbol, is_tradeable, quote_asset) after creating.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS venue_market (
    venue_market_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue            VARCHAR(32)  NOT NULL COMMENT 'e.g. bitvavo',
    market           VARCHAR(32)  NOT NULL COMMENT 'e.g. WLD-EUR',
    base_asset_id    INT(11)      NOT NULL,
    quote_currency   VARCHAR(8)   NOT NULL DEFAULT 'EUR',

    is_tradeable              TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Asset eligible for trading decisions on this venue',
    is_market_data_enabled    TINYINT(1) NOT NULL DEFAULT 1
        COMMENT 'Candle/ticker ETL enabled for this market',

    price_precision   SMALLINT UNSIGNED DEFAULT NULL,
    qty_precision     SMALLINT UNSIGNED DEFAULT NULL,
    min_order_qty     DECIMAL(20,10)    DEFAULT NULL,

    created_ts  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_venue_market (venue, market),
    KEY idx_venue_market_asset (base_asset_id),
    CONSTRAINT fk_venue_market_asset
        FOREIGN KEY (base_asset_id) REFERENCES asset (asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Venue-specific market metadata. Links to global asset via base_asset_id.';


-- ---------------------------------------------------------------------------
-- account_asset
-- One row per (trading_account, venue_market). All per-account asset settings.
-- Backfill: create rows for Joost account from existing balance/order snapshots.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_asset (
    account_asset_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    trading_account_id  BIGINT UNSIGNED NOT NULL,
    venue_market_id     BIGINT UNSIGNED NOT NULL,

    is_visible                  TINYINT(1) NOT NULL DEFAULT 1
        COMMENT 'Show in account dashboard',
    is_candidate_enabled        TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Eligible for signal-driven candidate selection for this account',
    is_order_proposal_enabled   TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Order proposals allowed for this account',
    is_portfolio_member         TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Asset part of this account portfolio focus set (replaces asset.is_portfolio)',
    is_hidden                   TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Suppressed from all views e.g. dust position',

    disabled_until_utc  DATETIME DEFAULT NULL
        COMMENT 'Temporarily suppress candidate eligibility until this timestamp',

    source  VARCHAR(32) NOT NULL DEFAULT 'MANUAL_ADD'
        COMMENT 'WALLET_DISCOVERY | OPEN_ORDER_DISCOVERY | MANUAL_ADD',

    created_ts  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_account_asset (trading_account_id, venue_market_id),
    KEY idx_account_asset_vm (venue_market_id),
    CONSTRAINT fk_account_asset_ta
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT fk_account_asset_vm
        FOREIGN KEY (venue_market_id) REFERENCES venue_market (venue_market_id),
    CONSTRAINT chk_account_asset_source
        CHECK (source IN ('WALLET_DISCOVERY', 'OPEN_ORDER_DISCOVERY', 'MANUAL_ADD'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Per-account asset settings. Each row scoped to one trading_account + venue_market.';
