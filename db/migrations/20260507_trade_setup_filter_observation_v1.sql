CREATE TABLE IF NOT EXISTS synth.trade_setup_filter_observation (
    trade_setup_filter_observation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asset_id INT NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    venue VARCHAR(32) NOT NULL,
    asof_ts_utc DATETIME(6) NOT NULL,
    context_ts_utc DATETIME(6) DEFAULT NULL,

    filter_name VARCHAR(64) NOT NULL,
    filter_version VARCHAR(32) NOT NULL,
    asset_suitability_mode VARCHAR(64) NOT NULL,

    selection_state VARCHAR(32) NOT NULL,
    selection_bias VARCHAR(32) DEFAULT NULL,
    selection_score DECIMAL(18,8) DEFAULT NULL,
    priority_rank INT DEFAULT NULL,

    btc_prior_24h DECIMAL(18,8) DEFAULT NULL,

    setup_filter_state VARCHAR(32) NOT NULL,
    setup_filter_reason VARCHAR(128) NOT NULL,
    target_horizon VARCHAR(32) NOT NULL,
    notes VARCHAR(512) DEFAULT NULL,

    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (trade_setup_filter_observation_id),
    UNIQUE KEY uq_trade_setup_filter_observation (
        asset_id,
        venue,
        asof_ts_utc,
        filter_name,
        filter_version,
        asset_suitability_mode
    ),
    KEY ix_trade_setup_filter_state (
        setup_filter_state,
        setup_filter_reason
    ),
    KEY ix_trade_setup_filter_ts (
        asof_ts_utc
    ),
    KEY ix_trade_setup_filter_symbol_ts (
        symbol,
        asof_ts_utc
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
