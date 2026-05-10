CREATE TABLE IF NOT EXISTS trading_account_balance_snapshot (
    trading_account_balance_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    snapshot_ts_utc DATETIME(6) NOT NULL DEFAULT UTC_TIMESTAMP(6),
    trading_account_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    currency_code VARCHAR(32) NOT NULL,
    available_amount DECIMAL(38,18) NOT NULL DEFAULT 0.000000000000000000,
    reserved_amount DECIMAL(38,18) NOT NULL DEFAULT 0.000000000000000000,
    total_amount DECIMAL(38,18) NOT NULL DEFAULT 0.000000000000000000,
    source_name VARCHAR(64) NOT NULL,
    raw_json LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (JSON_VALID(raw_json)),
    created_ts_utc DATETIME(6) NOT NULL DEFAULT UTC_TIMESTAMP(6),

    PRIMARY KEY (trading_account_balance_snapshot_id),

    UNIQUE KEY uq_trading_account_balance_snapshot_v1 (
        trading_account_id,
        venue,
        currency_code,
        snapshot_ts_utc
    ),

    KEY idx_trading_account_balance_latest_v1 (
        trading_account_id,
        venue,
        currency_code,
        snapshot_ts_utc
    ),

    KEY idx_trading_account_balance_currency_v1 (
        currency_code,
        snapshot_ts_utc
    ),

    CONSTRAINT fk_trading_account_balance_account_v1
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id),

    CONSTRAINT chk_trading_account_balance_amounts_v1
        CHECK (
            available_amount >= 0
            AND reserved_amount >= 0
            AND total_amount >= 0
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
