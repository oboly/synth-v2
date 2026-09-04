-- Canonical market-only ETH/BTC leadership snapshot (Issue #721, implementation
-- only; semantic/architecture owner remains Issue #305). No account or
-- execution coupling. Raw numeric return/ratio values are the primary output;
-- no leadership band/threshold is persisted.
CREATE TABLE IF NOT EXISTS eth_btc_leadership_snapshot_v1 (
    eth_btc_leadership_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asof_ts_utc DATETIME(6) NOT NULL,
    venue VARCHAR(32) NOT NULL,
    btc_market VARCHAR(32) NOT NULL,
    eth_market VARCHAR(32) NOT NULL,
    input_interval VARCHAR(16) NOT NULL,
    lookback_horizon VARCHAR(32) NOT NULL,
    effective_horizon VARCHAR(32) NOT NULL,
    model_id VARCHAR(64) NOT NULL,
    model_version VARCHAR(16) NOT NULL,
    freshness VARCHAR(32) NOT NULL,
    data_status VARCHAR(32) NOT NULL,
    btc_return_pct DECIMAL(24,10) NULL,
    eth_return_pct DECIMAL(24,10) NULL,
    eth_minus_btc_return_pct DECIMAL(24,10) NULL,
    eth_btc_ratio_start DECIMAL(30,15) NULL,
    eth_btc_ratio_end DECIMAL(30,15) NULL,
    eth_btc_ratio_change_pct DECIMAL(24,10) NULL,
    reason_codes JSON NOT NULL,
    provenance JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (eth_btc_leadership_snapshot_id),
    UNIQUE KEY uq_eth_btc_leadership_identity (asof_ts_utc, venue, btc_market, eth_market, input_interval, lookback_horizon, model_id, model_version),
    KEY idx_eth_btc_leadership_latest (venue, model_id, model_version, asof_ts_utc),
    CONSTRAINT chk_eth_btc_leadership_freshness CHECK (freshness IN ('FRESH', 'STALE', 'INSUFFICIENT_DATA')),
    CONSTRAINT chk_eth_btc_leadership_status CHECK (data_status IN ('AVAILABLE', 'INSUFFICIENT_DATA')),
    CONSTRAINT chk_eth_btc_leadership_horizon CHECK (effective_horizon IN ('UNKNOWN')),
    CONSTRAINT chk_eth_btc_leadership_numeric_pair CHECK (
        (data_status = 'AVAILABLE'
            AND btc_return_pct IS NOT NULL AND eth_return_pct IS NOT NULL
            AND eth_minus_btc_return_pct IS NOT NULL AND eth_btc_ratio_start IS NOT NULL
            AND eth_btc_ratio_end IS NOT NULL AND eth_btc_ratio_change_pct IS NOT NULL)
        OR
        (data_status = 'INSUFFICIENT_DATA'
            AND btc_return_pct IS NULL AND eth_return_pct IS NULL
            AND eth_minus_btc_return_pct IS NULL AND eth_btc_ratio_start IS NULL
            AND eth_btc_ratio_end IS NULL AND eth_btc_ratio_change_pct IS NULL)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Canonical market-only ETH/BTC leadership snapshot (#721 under #305); raw numeric primary output, no invented leadership bands.';
