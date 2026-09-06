-- Issue #753: immutable V1 trade -> canonical ShortTF Fib map binding.
CREATE TABLE IF NOT EXISTS fib_map_bound_trade_v1 (
    fib_map_bound_trade_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    binding_id VARCHAR(128) NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    market VARCHAR(64) NOT NULL,
    strategy_bucket_id VARCHAR(64) NOT NULL,
    strategy_id VARCHAR(128) NOT NULL,
    strategy_version VARCHAR(64) NOT NULL,
    trade_id VARCHAR(128) NOT NULL,
    source_execution_plan_id VARCHAR(128) NOT NULL,
    source_buy_fill_id VARCHAR(128) NOT NULL,
    native_map_id VARCHAR(128) NOT NULL,
    map_cycle_id VARCHAR(128) NOT NULL,
    map_structure_hash VARCHAR(128) NOT NULL,
    map_source_name VARCHAR(128) NOT NULL,
    map_source_version VARCHAR(64) NOT NULL,
    map_asof_ts_utc DATETIME(6) NOT NULL,
    map_published_at_utc DATETIME(6) NOT NULL,
    anchor_start_ts_utc DATETIME(6) NOT NULL,
    anchor_end_ts_utc DATETIME(6) NOT NULL,
    anchor_low_price DECIMAL(36,18) NOT NULL,
    anchor_high_price DECIMAL(36,18) NOT NULL,
    breakout_gate_price DECIMAL(36,18) NOT NULL,
    invalidation_price DECIMAL(36,18) NOT NULL,
    target_levels_json JSON NOT NULL,
    target_ladder_semantics_version VARCHAR(64) NOT NULL,
    bound_ts_utc DATETIME(6) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (fib_map_bound_trade_id),
    UNIQUE KEY uq_fib_map_bound_trade_binding (binding_id),
    UNIQUE KEY uq_fib_map_bound_trade_lineage (
        trading_account_id, venue, market, strategy_bucket_id,
        strategy_id, strategy_version, trade_id
    ),
    UNIQUE KEY uq_fib_map_bound_trade_source_fill (
        trading_account_id, venue, source_buy_fill_id
    ),
    KEY ix_fib_map_bound_trade_map (native_map_id, map_cycle_id),
    CONSTRAINT chk_fib_map_bound_trade_anchor CHECK (anchor_high_price > anchor_low_price),
    CONSTRAINT chk_fib_map_bound_trade_prices CHECK (
        anchor_low_price > 0 AND anchor_high_price > 0
        AND breakout_gate_price > 0 AND invalidation_price > 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
