-- Migration: active_regime_observation
-- Boundary: market-only · account-agnostic · no paper/live · no broker/order fields
-- Row grain: one row per (venue, interval_code, asof_ts_utc, asset_class, regime versions)
-- H1 context only, not advice. No policy_router. No execution intent.

CREATE TABLE IF NOT EXISTS active_regime_observation (
    active_regime_observation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue         VARCHAR(32)  NOT NULL,
    interval_code VARCHAR(16)  NOT NULL,
    asof_ts_utc   DATETIME(6)  NOT NULL,
    source_candle_ts_utc DATETIME(6)  NULL COMMENT 'close_ts_utc of BTC candle driving global_regime',

    -- Asset class dimension (one row per class per snapshot)
    asset_class  VARCHAR(32)  NOT NULL,
    asset_count  INT UNSIGNED NULL COMMENT 'number of assets in this class at this snapshot',

    -- Global regime
    global_regime         VARCHAR(64)  NOT NULL,
    global_regime_version VARCHAR(32)  NOT NULL,
    btc_return_24h_pct    DECIMAL(20,10) NULL,
    btc_return_72h_pct    DECIMAL(20,10) NULL,
    avg_alt_return_24h_pct DECIMAL(20,10) NULL COMMENT 'average 24h return across non-BTC assets',

    -- Asset class regime
    asset_class_regime         VARCHAR(64)  NOT NULL,
    asset_class_regime_version VARCHAR(32)  NOT NULL,
    class_return_24h_pct           DECIMAL(20,10) NULL,
    relative_class_vs_btc_24h_pct  DECIMAL(20,10) NULL,

    -- Compound cross key
    global_class_regime VARCHAR(128) NOT NULL,

    -- Hypothesis context tags (informational only — not routing, not advice)
    validated_hypothesis_tags_json LONGTEXT NULL,
    validation_status              VARCHAR(64)  NOT NULL,

    -- Audit
    source_ref_json LONGTEXT NULL,
    created_ts_utc  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_active_regime_obs (
        venue, interval_code, asof_ts_utc, asset_class,
        global_regime_version, asset_class_regime_version
    ),

    INDEX idx_asof    (asof_ts_utc, venue, interval_code),
    INDEX idx_global  (global_regime, asof_ts_utc),
    INDEX idx_class   (asset_class_regime, asof_ts_utc),
    INDEX idx_cross   (global_class_regime(64), asof_ts_utc),
    INDEX idx_status  (validation_status, asof_ts_utc)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Market-only regime observation. Account-agnostic. No paper/live. No broker/order fields.';
