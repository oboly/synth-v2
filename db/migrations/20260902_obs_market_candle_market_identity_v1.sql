-- Canonical public-candle identity retains the exchange market, not only its base asset.
-- Legacy rows without a deterministically recoverable market remain NULL and
-- are intentionally unavailable to market-specific consumers.
ALTER TABLE obs_market_candle
    ADD COLUMN IF NOT EXISTS market VARCHAR(32) NULL AFTER venue;

UPDATE obs_market_candle c
JOIN (
    SELECT venue, base_asset_id, MIN(market) AS market
    FROM venue_market
    GROUP BY venue, base_asset_id
    HAVING COUNT(*) = 1
) vm ON vm.venue = c.venue AND vm.base_asset_id = c.asset_id
SET c.market = vm.market
WHERE c.market IS NULL;

SET @legacy_unique_key := (
    SELECT index_name
    FROM (
        SELECT index_name, GROUP_CONCAT(column_name ORDER BY seq_in_index) AS columns_csv
        FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = "obs_market_candle" AND non_unique = 0
        GROUP BY index_name
        HAVING columns_csv = "asset_id,venue,interval_code,open_ts_utc"
    ) legacy_key
    LIMIT 1
);
SET @drop_legacy_unique := IF(
    @legacy_unique_key IS NULL,
    "SELECT 1",
    CONCAT("ALTER TABLE obs_market_candle DROP INDEX `", REPLACE(@legacy_unique_key, "`", "``"), "`")
);
PREPARE drop_legacy_unique FROM @drop_legacy_unique;
EXECUTE drop_legacy_unique;
DEALLOCATE PREPARE drop_legacy_unique;

ALTER TABLE obs_market_candle
    ADD UNIQUE KEY uq_obs_market_candle_venue_asset_market_interval_open
        (venue, asset_id, market, interval_code, open_ts_utc);
