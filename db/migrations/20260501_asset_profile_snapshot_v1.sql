CREATE TABLE IF NOT EXISTS asset_profile_snapshot (
    asset_profile_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
        COMMENT 'Surrogate primary key for one derived asset profile snapshot row.',

    asset_id BIGINT NOT NULL
        COMMENT 'Asset identifier from asset.asset_id. Static identity remains in asset; derived behavior lives here.',

    venue VARCHAR(32) NOT NULL
        COMMENT 'Trading/data venue for the measured profile, for example bitvavo.',

    interval_code VARCHAR(16) NOT NULL
        COMMENT 'Candle interval used for the profile calculation, for example 1h, 4h, or 1d.',

    asof_ts_utc DATETIME(6) NOT NULL
        COMMENT 'Point-in-time timestamp of the profile. Backtests must use profiles with asof_ts_utc <= replay time.',

    lookback_days INT NOT NULL
        COMMENT 'Number of calendar days used to derive the profile snapshot.',

    profile_version VARCHAR(64) NOT NULL
        COMMENT 'Version identifier of the profile engine that produced this row.',

    liquidity_score DECIMAL(20, 8) NULL
        COMMENT 'Derived tradability/liquidity score based on volume, trade activity, and data coverage.',

    liquidity_class VARCHAR(32) NULL
        COMMENT 'Derived liquidity tier such as MAJOR, LARGE_ALT, MID_ALT, SMALL_ALT, or MICRO_ALT.',

    beta_to_market DECIMAL(20, 8) NULL
        COMMENT 'Rolling sensitivity of this asset return versus the configured market benchmark basket.',

    beta_profile VARCHAR(32) NULL
        COMMENT 'Derived volatility/sensitivity behavior such as LOW_BETA, NORMAL_BETA, HIGH_BETA, or EXTREME_BETA.',

    realized_volatility DECIMAL(20, 8) NULL
        COMMENT 'Realized volatility estimate over the lookback window, normalized by interval where applicable.',

    sector_group_code VARCHAR(64) NULL
        COMMENT 'Empirical co-movement/rotation cluster. Intentionally nullable; v1 does not assign narrative sectors.',

    sector_confidence DECIMAL(10, 8) NULL
        COMMENT 'Confidence score for sector_group_code. In v1 this remains zero unless clustering is later enabled.',

    candles_observed INT NOT NULL DEFAULT 0
        COMMENT 'Number of candles observed for this asset in the profile lookback window.',

    coverage_ratio DECIMAL(10, 8) NULL
        COMMENT 'Observed candle count divided by expected candle count for the lookback and interval.',

    benchmark_symbols VARCHAR(255) NULL
        COMMENT 'Comma-separated benchmark symbols used for beta_to_market calculation.',

    notes TEXT NULL
        COMMENT 'Human-readable notes about profile assumptions, limitations, or engine behavior.',

    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        COMMENT 'UTC timestamp when this snapshot row was inserted.',

    PRIMARY KEY (asset_profile_snapshot_id),

    UNIQUE KEY uq_asset_profile_snapshot (
        asset_id,
        venue,
        interval_code,
        asof_ts_utc,
        lookback_days,
        profile_version
    ),

    KEY ix_asset_profile_lookup (
        asset_id,
        venue,
        interval_code,
        asof_ts_utc
    ),

    KEY ix_asset_profile_latest (
        venue,
        interval_code,
        asof_ts_utc
    ),

    KEY ix_asset_profile_liquidity (
        liquidity_class,
        liquidity_score
    ),

    KEY ix_asset_profile_beta (
        beta_profile,
        beta_to_market
    )
)
COMMENT='Point-in-time derived asset market profile snapshots. Separates static asset identity from dynamic liquidity, beta, volatility, and later empirical sector clustering. Research/backtest consumers must use point-in-time snapshots, never latest-only profiles.';

CREATE OR REPLACE VIEW vw_asset_profile_latest AS
SELECT aps.*
FROM asset_profile_snapshot aps
JOIN (
    SELECT
        asset_id,
        venue,
        interval_code,
        MAX(asof_ts_utc) AS max_asof_ts_utc
    FROM asset_profile_snapshot
    GROUP BY asset_id, venue, interval_code
) latest
  ON latest.asset_id = aps.asset_id
 AND latest.venue = aps.venue
 AND latest.interval_code = aps.interval_code
 AND latest.max_asof_ts_utc = aps.asof_ts_utc;
