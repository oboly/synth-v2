-- Issue #752 B3: append-only cumulative fill reconciliation facts.
-- Migration artifact only; no broker writes or order authority.
CREATE TABLE IF NOT EXISTS strategy_owned_fill_reconciliation_fact_v1 (
    strategy_owned_fill_reconciliation_fact_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    fact_id VARCHAR(128) NOT NULL,
    source_snapshot_id VARCHAR(128) NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    market VARCHAR(64) NOT NULL,
    strategy_bucket_id VARCHAR(64) NOT NULL,
    strategy_id VARCHAR(128) NOT NULL,
    strategy_version VARCHAR(64) NOT NULL,
    trade_id VARCHAR(128) NOT NULL,
    source_execution_plan_id VARCHAR(128) NOT NULL,
    source_order_id VARCHAR(128) NOT NULL,
    side VARCHAR(8) NOT NULL,
    cumulative_filled_base_quantity DECIMAL(36,18) NOT NULL,
    attributed_delta_base_quantity DECIMAL(36,18) NOT NULL,
    emitted_event_id VARCHAR(128) NULL,
    observed_ts_utc DATETIME(6) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (strategy_owned_fill_reconciliation_fact_id),
    UNIQUE KEY uq_strategy_fill_reconciliation_fact (fact_id),
    UNIQUE KEY uq_strategy_fill_reconciliation_snapshot (
        trading_account_id, venue, source_order_id, source_snapshot_id
    ),
    KEY ix_strategy_fill_reconciliation_order (
        trading_account_id, venue, source_order_id, observed_ts_utc
    ),
    CONSTRAINT chk_strategy_fill_reconciliation_side CHECK (side IN ('BUY','SELL')),
    CONSTRAINT chk_strategy_fill_reconciliation_cumulative CHECK (cumulative_filled_base_quantity >= 0),
    CONSTRAINT chk_strategy_fill_reconciliation_delta CHECK (attributed_delta_base_quantity >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
