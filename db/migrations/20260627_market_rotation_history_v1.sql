-- Migration: market_rotation_history_v1
-- Boundary: research-only · market-only · account-agnostic
--           no FK to account_asset, account_balance, trading_account, or order tables
--           no broker calls · no execution logic
--
-- Purpose: append-only market rotation history built from obs_market_candle 1h data,
--          plus one optional global crypto-market context row per hourly run.
--
-- Tables:
--   1. market_rotation_snapshot_v1    — one header per (as_of_ts_utc, horizon_h, venue)
--   2. market_rotation_observation_v1 — one observation per (snapshot_id, asset_id)
--   3. market_global_snapshot_v1      — one CoinGecko global row per (as_of_ts_utc, provider_name)
--
-- Idempotency:
--   Tables 1 and 2 use INSERT IGNORE. Repeat runs produce zero new rows.
--   Table 3 uses a conditional write: INSERT on first write; UPDATE only to promote
--   UNAVAILABLE/SKIPPED_NO_CREDENTIAL to AVAILABLE; existing AVAILABLE rows are immutable.
--
-- Safety markers:
--   broker_private_calls=0  broker_writes=0  order_submission=0
--   live_orders=0  decision_gate=none  execution_planner=none  executor=none


-- ---------------------------------------------------------------------------
-- 1. market_rotation_snapshot_v1
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_rotation_snapshot_v1 (
    snapshot_id              BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,

    as_of_ts_utc             DATETIME(6)       NOT NULL
        COMMENT 'Snapshot anchor: latest closed-candle UTC hour boundary',
    horizon_h                SMALLINT UNSIGNED NOT NULL
        COMMENT '24 = 24h horizon, 168 = 7d horizon',
    venue                    VARCHAR(32)       NOT NULL DEFAULT 'bitvavo',
    candle_interval_code     VARCHAR(8)        NOT NULL DEFAULT '1h',

    eligible_market_count    SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    excluded_market_count    SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    observation_count        SMALLINT UNSIGNED NOT NULL DEFAULT 0,

    created_at               DATETIME(6)       NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (snapshot_id),

    UNIQUE KEY uq_mrh_snapshot (as_of_ts_utc, horizon_h, venue),

    KEY idx_mrh_snapshot_horizon (horizon_h, as_of_ts_utc)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Market rotation history snapshot headers. One row per (as_of_ts_utc, horizon_h, venue).';


-- ---------------------------------------------------------------------------
-- 2. market_rotation_observation_v1
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_rotation_observation_v1 (
    obs_id                         BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,

    snapshot_id                    BIGINT UNSIGNED   NOT NULL
        COMMENT 'Logical ref to market_rotation_snapshot_v1.snapshot_id — no FK',
    asset_id                       INT               NOT NULL
        COMMENT 'Logical ref to asset.asset_id — no FK',
    market                         VARCHAR(32)       NOT NULL
        COMMENT 'e.g. BTC-EUR',
    horizon_h                      SMALLINT UNSIGNED NOT NULL,

    window_open_ts_utc             DATETIME(6)       NOT NULL
        COMMENT 'open_ts_utc of first actual candle in current horizon window',
    window_close_ts_utc            DATETIME(6)       NOT NULL
        COMMENT 'close_ts_utc of last actual candle in current horizon window',

    price_open                     DECIMAL(28, 10)   NOT NULL
        COMMENT 'close_price of last candle in baseline window (horizon-start reference)',
    price_close                    DECIMAL(28, 10)   NOT NULL
        COMMENT 'close_price of last candle in current horizon window',
    price_change_pct               DECIMAL(18, 6)    NOT NULL
        COMMENT '(price_close - price_open) / price_open * 100',

    quote_volume                   DECIMAL(28, 6)    NOT NULL
        COMMENT 'SUM(volume_quote_eur) over current horizon window',
    baseline_quote_volume          DECIMAL(28, 6)    NOT NULL
        COMMENT 'SUM(volume_quote_eur) over preceding comparable baseline window',
    relative_volume                DECIMAL(18, 6)    NOT NULL
        COMMENT 'quote_volume / baseline_quote_volume',

    candle_count                   SMALLINT UNSIGNED NOT NULL,
    expected_candle_count          SMALLINT UNSIGNED NOT NULL
        COMMENT '= horizon_h (one 1h candle per hour)',
    coverage_ratio                 DECIMAL(6, 4)     NOT NULL
        COMMENT 'candle_count / expected_candle_count',

    baseline_candle_count          SMALLINT UNSIGNED NOT NULL,
    baseline_expected_candle_count SMALLINT UNSIGNED NOT NULL,
    baseline_coverage_ratio        DECIMAL(6, 4)     NOT NULL,

    as_of_ts_utc                   DATETIME(6)       NOT NULL
        COMMENT 'Denormalized from snapshot header for per-observation audit queries',

    PRIMARY KEY (obs_id),

    UNIQUE KEY uq_mrh_obs (snapshot_id, asset_id),

    KEY idx_mrh_obs_as_of  (as_of_ts_utc, horizon_h),
    KEY idx_mrh_obs_asset  (asset_id, as_of_ts_utc),
    KEY idx_mrh_obs_market (market, horizon_h, as_of_ts_utc)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Market rotation history per-market observations. Append-only. No account coupling.';


-- ---------------------------------------------------------------------------
-- 3. market_global_snapshot_v1
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_global_snapshot_v1 (
    global_ctx_id               BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,

    as_of_ts_utc                DATETIME(6)      NOT NULL
        COMMENT 'Same UTC hourly bucket as the market rotation run',
    provider_name               VARCHAR(64)      NOT NULL DEFAULT 'coingecko',

    source_status               VARCHAR(32)      NOT NULL
        COMMENT 'AVAILABLE | UNAVAILABLE | SKIPPED_NO_CREDENTIAL',
    source_error_reason         VARCHAR(512)     NULL
        COMMENT 'Short error code when UNAVAILABLE; NULL otherwise',

    total_volume_24h_usd        DECIMAL(28, 2)   NULL
        COMMENT 'data.total_volume.usd',
    volume_change_pct_24h       DECIMAL(10, 4)   NULL
        COMMENT 'data.volume_change_percentage_24h_usd',
    total_market_cap_usd        DECIMAL(28, 2)   NULL
        COMMENT 'data.total_market_cap.usd',
    market_cap_change_pct_24h   DECIMAL(10, 4)   NULL
        COMMENT 'data.market_cap_change_percentage_24h_usd',
    btc_dominance_pct           DECIMAL(8, 4)    NULL
        COMMENT 'data.market_cap_percentage.btc',
    eth_dominance_pct           DECIMAL(8, 4)    NULL
        COMMENT 'data.market_cap_percentage.eth',

    provider_updated_at_utc     DATETIME(6)      NULL
        COMMENT 'data.updated_at parsed from Unix timestamp',
    fetched_at_utc              DATETIME(6)      NOT NULL
        COMMENT 'UTC wall-clock time the HTTP response was received',

    created_at                  DATETIME(6)      NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (global_ctx_id),

    UNIQUE KEY uq_global_ctx (as_of_ts_utc, provider_name),

    KEY idx_global_ctx_as_of (as_of_ts_utc),

    CONSTRAINT chk_global_ctx_status
        CHECK (source_status IN ('AVAILABLE', 'UNAVAILABLE', 'SKIPPED_NO_CREDENTIAL'))

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Global crypto market context. One row per UTC hourly bucket and provider. Append-only.';
