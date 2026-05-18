CREATE TABLE IF NOT EXISTS market_price_snapshot (
    market_price_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    venue VARCHAR(32) NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    market VARCHAR(64) NOT NULL,
    quote_currency VARCHAR(16) NOT NULL,
    price DECIMAL(36,18) NOT NULL,
    source_name VARCHAR(96) NOT NULL,
    source_ts_utc DATETIME(6) NULL,
    observed_ts_utc DATETIME(6) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (market_price_snapshot_id),

    UNIQUE KEY uq_market_price_snapshot_observed (
        venue,
        symbol,
        quote_currency,
        source_name,
        observed_ts_utc
    ),

    KEY ix_market_price_snapshot_latest (
        venue,
        symbol,
        quote_currency,
        observed_ts_utc
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
