-- Canonical market-only MOMENTUM evidence snapshot (#741, resolving #729's
-- BUILD_MINIMAL_CANONICAL_OWNER decision). Raw MACD/signal/histogram
-- primitives only; no categorical momentum states. No account or execution
-- coupling.
CREATE TABLE IF NOT EXISTS momentum_evidence_snapshot_v1 (
    momentum_evidence_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asof_ts_utc DATETIME(6) NULL,
    venue VARCHAR(32) NOT NULL,
    asset_id INT UNSIGNED NOT NULL,
    market VARCHAR(64) NOT NULL,
    input_interval VARCHAR(16) NOT NULL,
    lookback_horizon VARCHAR(64) NOT NULL,
    effective_horizon VARCHAR(32) NOT NULL,
    observed_lifecycle_status VARCHAR(32) NOT NULL,
    fast_ema_period SMALLINT UNSIGNED NOT NULL,
    slow_ema_period SMALLINT UNSIGNED NOT NULL,
    signal_ema_period SMALLINT UNSIGNED NOT NULL,
    macd_value DECIMAL(24,10) NULL,
    signal_value DECIMAL(24,10) NULL,
    histogram_value DECIMAL(24,10) NULL,
    histogram_delta DECIMAL(24,10) NULL,
    freshness VARCHAR(32) NOT NULL,
    data_quality VARCHAR(32) NOT NULL,
    model_id VARCHAR(64) NOT NULL,
    model_version VARCHAR(16) NOT NULL,
    status VARCHAR(32) NOT NULL,
    reason_codes_json LONGTEXT NULL,
    provenance_payload LONGTEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (momentum_evidence_snapshot_id),
    UNIQUE KEY uq_momentum_evidence_identity (venue, asset_id, market, input_interval, asof_ts_utc, model_id, model_version),
    KEY idx_momentum_evidence_latest (venue, asset_id, model_id, model_version, asof_ts_utc),
    CONSTRAINT chk_momentum_evidence_periods CHECK (fast_ema_period > 0 AND slow_ema_period > fast_ema_period AND signal_ema_period > 0),
    CONSTRAINT chk_momentum_evidence_status CHECK (status IN ('VALID', 'STALE', 'INSUFFICIENT_DATA')),
    CONSTRAINT chk_momentum_evidence_freshness CHECK (freshness IN ('FRESH', 'STALE', 'INSUFFICIENT_DATA', 'UNKNOWN')),
    CONSTRAINT chk_momentum_evidence_horizon CHECK (effective_horizon IN ('VERY_SHORT', 'SHORT', 'MID', 'LONG', 'REGIME', 'MULTI_HORIZON', 'UNKNOWN')),
    CONSTRAINT chk_momentum_evidence_data_quality CHECK (
        data_quality IN (
            'OK', 'FUTURE_ASOF', 'MISSING_SOURCE_CANDLE', 'STALE_SOURCE_CANDLE',
            'MALFORMED_SOURCE_CANDLE', 'INSUFFICIENT_WARMUP',
            'NON_FINITE_COMPUTED_VALUE', 'UNSUPPORTED_INTERVAL'
        )
    ),
    CONSTRAINT chk_momentum_evidence_raw_pairing CHECK (
        (macd_value IS NULL AND signal_value IS NULL AND histogram_value IS NULL AND histogram_delta IS NULL)
        OR (macd_value IS NOT NULL AND signal_value IS NOT NULL AND histogram_value IS NOT NULL AND histogram_delta IS NOT NULL)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Canonical market-only MOMENTUM evidence (#741); raw MACD/signal/histogram primary output, no categorical states.';
