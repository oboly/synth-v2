-- =====================================================================
-- SYNTH CORE LAYERED SCHEMA
-- Version: v1.0
-- Target: MariaDB
-- Notes:
-- - UTC everywhere
-- - EUR default where relevant for execution/trading context
-- - Observation -> Feature -> Interpretation -> Strategy -> Decision
-- =====================================================================

SET NAMES utf8mb4;
SET time_zone = '+00:00';

CREATE TABLE IF NOT EXISTS asset (
    asset_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    symbol VARCHAR(32) NOT NULL,
    base_symbol VARCHAR(32) NOT NULL,
    quote_symbol VARCHAR(32) NOT NULL DEFAULT 'EUR',
    asset_name VARCHAR(128) NULL,
    sector VARCHAR(64) NULL,
    is_enabled TINYINT(1) NOT NULL DEFAULT 1,
    is_portfolio TINYINT(1) NOT NULL DEFAULT 0,
    is_core_sensor TINYINT(1) NOT NULL DEFAULT 0,
    created_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (asset_id),
    UNIQUE KEY uq_asset_symbol_quote (symbol, quote_symbol),
    KEY ix_asset_enabled (is_enabled),
    KEY ix_asset_sector (sector)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS market_candle (
    candle_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asset_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL DEFAULT 'bitvavo',
    interval_code VARCHAR(16) NOT NULL,
    open_ts_utc DATETIME NOT NULL,
    close_ts_utc DATETIME NOT NULL,
    open_price DECIMAL(28,10) NOT NULL,
    high_price DECIMAL(28,10) NOT NULL,
    low_price DECIMAL(28,10) NOT NULL,
    close_price DECIMAL(28,10) NOT NULL,
    volume_base DECIMAL(38,18) NULL,
    volume_quote_eur DECIMAL(38,10) NULL,
    trade_count INT NULL,
    source_ts_utc DATETIME NULL,
    ingest_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (candle_id),
    UNIQUE KEY uq_market_candle (asset_id, venue, interval_code, open_ts_utc),
    KEY ix_market_candle_lookup (asset_id, interval_code, close_ts_utc),
    CONSTRAINT fk_market_candle_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS venue_ticker_24h (
    ticker_24h_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asset_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL DEFAULT 'bitvavo',
    snapshot_ts_utc DATETIME NOT NULL,
    last_price DECIMAL(28,10) NULL,
    bid_price DECIMAL(28,10) NULL,
    ask_price DECIMAL(28,10) NULL,
    open_24h_price DECIMAL(28,10) NULL,
    high_24h_price DECIMAL(28,10) NULL,
    low_24h_price DECIMAL(28,10) NULL,
    volume_base_24h DECIMAL(38,18) NULL,
    volume_quote_eur_24h DECIMAL(38,10) NULL,
    spread_abs DECIMAL(28,10) NULL,
    spread_bps DECIMAL(18,8) NULL,
    ingest_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker_24h_id),
    UNIQUE KEY uq_venue_ticker_24h (asset_id, venue, snapshot_ts_utc),
    KEY ix_venue_ticker_24h_lookup (asset_id, venue, snapshot_ts_utc),
    CONSTRAINT fk_venue_ticker_24h_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS asset_market_snapshot (
    asset_market_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asset_id BIGINT UNSIGNED NOT NULL,
    provider VARCHAR(32) NOT NULL DEFAULT 'coingecko',
    snapshot_ts_utc DATETIME NOT NULL,
    price_usd DECIMAL(28,10) NULL,
    market_cap_usd DECIMAL(38,2) NULL,
    total_volume_usd_24h DECIMAL(38,2) NULL,
    circulating_supply DECIMAL(38,10) NULL,
    total_supply DECIMAL(38,10) NULL,
    max_supply DECIMAL(38,10) NULL,
    market_cap_rank INT NULL,
    ingest_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (asset_market_snapshot_id),
    UNIQUE KEY uq_asset_market_snapshot (asset_id, provider, snapshot_ts_utc),
    KEY ix_asset_market_snapshot_lookup (asset_id, provider, snapshot_ts_utc),
    CONSTRAINT fk_asset_market_snapshot_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS market_global_snapshot (
    market_global_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    provider VARCHAR(32) NOT NULL DEFAULT 'coingecko',
    snapshot_ts_utc DATETIME NOT NULL,
    total_market_cap_usd DECIMAL(38,2) NULL,
    total_volume_usd_24h DECIMAL(38,2) NULL,
    btc_dominance_pct DECIMAL(10,4) NULL,
    eth_dominance_pct DECIMAL(10,4) NULL,
    altcoin_market_cap_usd DECIMAL(38,2) NULL,
    ingest_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (market_global_snapshot_id),
    UNIQUE KEY uq_market_global_snapshot (provider, snapshot_ts_utc),
    KEY ix_market_global_snapshot_lookup (provider, snapshot_ts_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS breathline_input (
    breathline_input_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asset_id BIGINT UNSIGNED NULL,
    scope_symbol VARCHAR(32) NULL,
    event_ts_utc DATETIME NOT NULL,
    horizon_label VARCHAR(64) NULL,
    phase_label VARCHAR(64) NULL,
    coherence_label VARCHAR(64) NULL,
    directional_bias VARCHAR(64) NULL,
    context_text TEXT NULL,
    source_label VARCHAR(128) NULL,
    ingest_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (breathline_input_id),
    KEY ix_breathline_input_asset_ts (asset_id, event_ts_utc),
    KEY ix_breathline_input_scope_ts (scope_symbol, event_ts_utc),
    CONSTRAINT fk_breathline_input_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS candle_feat (
    candle_feat_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    candle_id BIGINT UNSIGNED NOT NULL,
    asset_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL DEFAULT 'bitvavo',
    interval_code VARCHAR(16) NOT NULL,
    close_ts_utc DATETIME NOT NULL,
    ema_20 DECIMAL(28,10) NULL,
    ema_50 DECIMAL(28,10) NULL,
    rsi_14 DECIMAL(18,8) NULL,
    atr_14 DECIMAL(28,10) NULL,
    volume_ratio_20 DECIMAL(18,8) NULL,
    volume_zscore_20 DECIMAL(18,8) NULL,
    obv DECIMAL(38,10) NULL,
    obv_slope_5 DECIMAL(18,8) NULL,
    dollar_volume_ratio_20 DECIMAL(18,8) NULL,
    created_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (candle_feat_id),
    UNIQUE KEY uq_candle_feat_candle (candle_id),
    KEY ix_candle_feat_lookup (asset_id, interval_code, close_ts_utc),
    CONSTRAINT fk_candle_feat_candle
        FOREIGN KEY (candle_id) REFERENCES market_candle(candle_id),
    CONSTRAINT fk_candle_feat_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS interpreter_state (
    interpreter_state_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asset_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NULL DEFAULT 'bitvavo',
    interval_code VARCHAR(16) NULL,
    state_ts_utc DATETIME NOT NULL,
    regime_state VARCHAR(64) NULL,
    phase_state VARCHAR(64) NULL,
    trend_volume_state VARCHAR(64) NULL,
    sector_rotation_state VARCHAR(64) NULL,
    breathline_alignment_state VARCHAR(64) NULL,
    confidence_score DECIMAL(10,6) NULL,
    reason_code VARCHAR(128) NULL,
    summary_text VARCHAR(512) NULL,
    created_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (interpreter_state_id),
    UNIQUE KEY uq_interpreter_state (asset_id, venue, interval_code, state_ts_utc),
    KEY ix_interpreter_state_lookup (asset_id, interval_code, state_ts_utc),
    KEY ix_interpreter_state_regime (regime_state),
    CONSTRAINT fk_interpreter_state_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS strategy_signal (
    strategy_signal_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asset_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NULL DEFAULT 'bitvavo',
    interval_code VARCHAR(16) NULL,
    signal_ts_utc DATETIME NOT NULL,
    strategy_name VARCHAR(128) NOT NULL,
    signal_state VARCHAR(64) NOT NULL,
    confidence_score DECIMAL(10,6) NULL,
    reason_code VARCHAR(128) NULL,
    trend_strength_state VARCHAR(64) NULL,
    price_volume_state VARCHAR(64) NULL,
    phase_state VARCHAR(64) NULL,
    interpreter_state_id BIGINT UNSIGNED NULL,
    summary_text VARCHAR(512) NULL,
    created_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (strategy_signal_id),
    UNIQUE KEY uq_strategy_signal (asset_id, strategy_name, venue, interval_code, signal_ts_utc),
    KEY ix_strategy_signal_lookup (asset_id, strategy_name, signal_ts_utc),
    KEY ix_strategy_signal_state (signal_state),
    CONSTRAINT fk_strategy_signal_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id),
    CONSTRAINT fk_strategy_signal_interpreter_state
        FOREIGN KEY (interpreter_state_id) REFERENCES interpreter_state(interpreter_state_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS decision_log (
    decision_log_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asset_id BIGINT UNSIGNED NOT NULL,
    decision_ts_utc DATETIME NOT NULL,
    strategy_signal_id BIGINT UNSIGNED NULL,
    strategy_used VARCHAR(128) NULL,
    decision_type VARCHAR(64) NOT NULL,
    action_state VARCHAR(64) NOT NULL,
    blocked_by VARCHAR(128) NULL,
    approved_by VARCHAR(128) NULL,
    summary_text VARCHAR(512) NOT NULL,
    created_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (decision_log_id),
    KEY ix_decision_log_lookup (asset_id, decision_ts_utc),
    KEY ix_decision_log_action (action_state),
    KEY ix_decision_log_strategy (strategy_used),
    CONSTRAINT fk_decision_log_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id),
    CONSTRAINT fk_decision_log_strategy_signal
        FOREIGN KEY (strategy_signal_id) REFERENCES strategy_signal(strategy_signal_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS position_snapshot (
    position_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asset_id BIGINT UNSIGNED NOT NULL,
    snapshot_ts_utc DATETIME NOT NULL,
    quantity DECIMAL(38,18) NOT NULL DEFAULT 0,
    avg_entry_price_eur DECIMAL(28,10) NULL,
    market_value_eur DECIMAL(38,10) NULL,
    unrealized_pnl_eur DECIMAL(38,10) NULL,
    created_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (position_snapshot_id),
    UNIQUE KEY uq_position_snapshot (asset_id, snapshot_ts_utc),
    KEY ix_position_snapshot_lookup (asset_id, snapshot_ts_utc),
    CONSTRAINT fk_position_snapshot_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE OR REPLACE VIEW v_latest_market_candle AS
SELECT mc.*
FROM market_candle mc
JOIN (
    SELECT asset_id, venue, interval_code, MAX(open_ts_utc) AS max_open_ts_utc
    FROM market_candle
    GROUP BY asset_id, venue, interval_code
) x
  ON x.asset_id = mc.asset_id
 AND x.venue = mc.venue
 AND x.interval_code = mc.interval_code
 AND x.max_open_ts_utc = mc.open_ts_utc;

CREATE OR REPLACE VIEW v_latest_candle_feat AS
SELECT cf.*
FROM candle_feat cf
JOIN (
    SELECT asset_id, venue, interval_code, MAX(close_ts_utc) AS max_close_ts_utc
    FROM candle_feat
    GROUP BY asset_id, venue, interval_code
) x
  ON x.asset_id = cf.asset_id
 AND x.venue = cf.venue
 AND x.interval_code = cf.interval_code
 AND x.max_close_ts_utc = cf.close_ts_utc;

CREATE OR REPLACE VIEW v_latest_interpreter_state AS
SELECT i.*
FROM interpreter_state i
JOIN (
    SELECT asset_id, venue, interval_code, MAX(state_ts_utc) AS max_state_ts_utc
    FROM interpreter_state
    GROUP BY asset_id, venue, interval_code
) x
  ON x.asset_id = i.asset_id
 AND ((x.venue = i.venue) OR (x.venue IS NULL AND i.venue IS NULL))
 AND ((x.interval_code = i.interval_code) OR (x.interval_code IS NULL AND i.interval_code IS NULL))
 AND x.max_state_ts_utc = i.state_ts_utc;

CREATE OR REPLACE VIEW v_latest_strategy_signal AS
SELECT s.*
FROM strategy_signal s
JOIN (
    SELECT asset_id, strategy_name, venue, interval_code, MAX(signal_ts_utc) AS max_signal_ts_utc
    FROM strategy_signal
    GROUP BY asset_id, strategy_name, venue, interval_code
) x
  ON x.asset_id = s.asset_id
 AND x.strategy_name = s.strategy_name
 AND ((x.venue = s.venue) OR (x.venue IS NULL AND s.venue IS NULL))
 AND ((x.interval_code = s.interval_code) OR (x.interval_code IS NULL AND s.interval_code IS NULL))
 AND x.max_signal_ts_utc = s.signal_ts_utc;

CREATE OR REPLACE VIEW v_latest_decision_log AS
SELECT d.*
FROM decision_log d
JOIN (
    SELECT asset_id, MAX(decision_ts_utc) AS max_decision_ts_utc
    FROM decision_log
    GROUP BY asset_id
) x
  ON x.asset_id = d.asset_id
 AND x.max_decision_ts_utc = d.decision_ts_utc;
