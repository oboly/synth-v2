-- Additive canonical market-keyed public-candle projection for consumers that
-- require exact venue-market identity. The legacy obs_market_candle key remains unchanged.
CREATE TABLE IF NOT EXISTS obs_market_candle_market_identity_v1 (
    asset_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    market VARCHAR(32) NOT NULL,
    interval_code VARCHAR(16) NOT NULL,
    open_ts_utc DATETIME(6) NOT NULL,
    close_ts_utc DATETIME(6) NOT NULL,
    open_price DECIMAL(18,8) NOT NULL,
    high_price DECIMAL(18,8) NOT NULL,
    low_price DECIMAL(18,8) NOT NULL,
    close_price DECIMAL(18,8) NOT NULL,
    volume_base DECIMAL(28,12) NOT NULL,
    PRIMARY KEY (venue, asset_id, market, interval_code, open_ts_utc),
    KEY idx_obs_market_candle_market_identity_asof (venue, market, interval_code, close_ts_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO obs_market_candle_market_identity_v1 (
    asset_id, venue, market, interval_code, open_ts_utc, close_ts_utc,
    open_price, high_price, low_price, close_price, volume_base
)
SELECT c.asset_id, c.venue, vm.market, c.interval_code, c.open_ts_utc, c.close_ts_utc,
       c.open_price, c.high_price, c.low_price, c.close_price, c.volume_base
FROM obs_market_candle c
JOIN venue_market vm ON vm.venue=c.venue AND vm.base_asset_id=c.asset_id
JOIN (
    SELECT venue, base_asset_id FROM venue_market GROUP BY venue, base_asset_id HAVING COUNT(*)=1
) only_market ON only_market.venue=vm.venue AND only_market.base_asset_id=vm.base_asset_id;
