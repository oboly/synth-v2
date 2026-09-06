-- Issue #752: append-only strategy-owned inventory attribution facts.
-- Migration artifact only; no broker writes or order authority.
CREATE TABLE IF NOT EXISTS strategy_owned_inventory_event_v1 (
    strategy_owned_inventory_event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    event_id VARCHAR(128) NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    market VARCHAR(64) NOT NULL,
    strategy_bucket_id VARCHAR(64) NOT NULL,
    strategy_id VARCHAR(128) NOT NULL,
    strategy_version VARCHAR(64) NOT NULL,
    trade_id VARCHAR(128) NOT NULL,
    source_execution_plan_id VARCHAR(128) NOT NULL,
    source_fill_id VARCHAR(128) NOT NULL,
    side VARCHAR(8) NOT NULL,
    filled_base_quantity DECIMAL(36,18) NOT NULL,
    fill_notional_eur DECIMAL(36,18) NULL,
    occurred_ts_utc DATETIME(6) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (strategy_owned_inventory_event_id),
    UNIQUE KEY uq_strategy_inventory_event_id (event_id),
    UNIQUE KEY uq_strategy_inventory_fill (trading_account_id, venue, source_fill_id),
    KEY ix_strategy_inventory_lineage (trading_account_id, venue, market, strategy_bucket_id, trade_id),
    CONSTRAINT chk_strategy_inventory_side CHECK (side IN ('BUY','SELL')),
    CONSTRAINT chk_strategy_inventory_qty CHECK (filled_base_quantity > 0),
    CONSTRAINT chk_strategy_inventory_notional CHECK (fill_notional_eur IS NULL OR fill_notional_eur >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
