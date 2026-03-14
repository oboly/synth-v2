-- Synth v1 core schema
-- UTC storage only
-- EUR default where quote currency is relevant

CREATE TABLE IF NOT EXISTS asset (
    asset_id          INT AUTO_INCREMENT PRIMARY KEY,
    symbol            VARCHAR(16) NOT NULL,
    name              VARCHAR(64) NULL,
    sector            VARCHAR(32) NULL,

    is_enabled        TINYINT(1) NOT NULL DEFAULT 1,
    is_portfolio      TINYINT(1) NOT NULL DEFAULT 0,
    is_core_sensor    TINYINT(1) NOT NULL DEFAULT 0,

    created_ts        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_asset_symbol (symbol),
    KEY idx_asset_enabled (is_enabled),
    KEY idx_asset_portfolio (is_portfolio),
    KEY idx_asset_core_sensor (is_core_sensor),
    KEY idx_asset_sector (sector)
);

CREATE TABLE IF NOT EXISTS market_candle (
    asset_id          INT NOT NULL,
    venue             VARCHAR(32) NOT NULL,
    interval_code     VARCHAR(16) NOT NULL,
    ts_open_utc       DATETIME NOT NULL,
    ts_close_utc      DATETIME NOT NULL,

    open_price        DECIMAL(28,12) NOT NULL,
    high_price        DECIMAL(28,12) NOT NULL,
    low_price         DECIMAL(28,12) NOT NULL,
    close_price       DECIMAL(28,12) NOT NULL,
    volume_base       DECIMAL(28,12) NULL,
    volume_quote_eur  DECIMAL(28,12) NULL,

    created_ts        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (asset_id, venue, interval_code, ts_open_utc),
    KEY idx_candle_close (asset_id, interval_code, ts_close_utc),
    CONSTRAINT fk_candle_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

CREATE TABLE IF NOT EXISTS candle_feat (
    asset_id            INT NOT NULL,
    venue               VARCHAR(32) NOT NULL,
    interval_code       VARCHAR(16) NOT NULL,
    ts_open_utc         DATETIME NOT NULL,

    sma_20              DECIMAL(28,12) NULL,
    ema_20              DECIMAL(28,12) NULL,
    ema_50              DECIMAL(28,12) NULL,
    rsi_14              DECIMAL(10,6) NULL,
    atr_14              DECIMAL(28,12) NULL,
    bb_width_20         DECIMAL(18,10) NULL,
    rel_strength_score  DECIMAL(18,10) NULL,
    volatility_score    DECIMAL(18,10) NULL,

    created_ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                      ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (asset_id, venue, interval_code, ts_open_utc),
    CONSTRAINT fk_feat_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

CREATE TABLE IF NOT EXISTS strategy_signal (
    signal_id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    asset_id            INT NOT NULL,
    strategy_name       VARCHAR(64) NOT NULL,
    timeframe_code      VARCHAR(16) NOT NULL,
    signal_ts_utc       DATETIME NOT NULL,

    signal_state        VARCHAR(32) NOT NULL,
    signal_score        DECIMAL(10,6) NULL,
    confidence_score    DECIMAL(10,6) NULL,
    bias_side           VARCHAR(16) NULL,
    reason_code         VARCHAR(64) NULL,
    reason_text         TEXT NULL,

    created_ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_signal_asset_ts (asset_id, signal_ts_utc),
    KEY idx_signal_strategy_ts (strategy_name, signal_ts_utc),
    CONSTRAINT fk_signal_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

CREATE TABLE IF NOT EXISTS decision_log (
    decision_id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    asset_id            INT NULL,
    decision_ts_utc     DATETIME NOT NULL,

    module_name         VARCHAR(64) NOT NULL,
    decision_type       VARCHAR(32) NOT NULL,
    action_state        VARCHAR(32) NOT NULL,
    blocked_by          VARCHAR(64) NULL,

    summary_text        TEXT NULL,
    detail_json         JSON NULL,

    created_ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_decision_ts (decision_ts_utc),
    KEY idx_decision_asset_ts (asset_id, decision_ts_utc),
    CONSTRAINT fk_decision_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

CREATE TABLE IF NOT EXISTS position_snapshot (
    snapshot_id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    asset_id            INT NOT NULL,
    snapshot_ts_utc     DATETIME NOT NULL,

    quantity            DECIMAL(28,12) NOT NULL,
    avg_entry_price_eur DECIMAL(28,12) NULL,
    market_price_eur    DECIMAL(28,12) NULL,
    market_value_eur    DECIMAL(28,12) NULL,
    pnl_unrealized_eur  DECIMAL(28,12) NULL,
    pnl_unrealized_pct  DECIMAL(18,10) NULL,

    created_ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_pos_asset_ts (asset_id, snapshot_ts_utc),
    CONSTRAINT fk_position_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

CREATE TABLE IF NOT EXISTS breathline_compass (
    compass_id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    prediction_ts_utc    DATETIME NOT NULL,
    source_name          VARCHAR(32) NOT NULL,

    asset_id             INT NULL,
    scope_type           VARCHAR(16) NOT NULL,
    target_year          INT NULL,
    target_month         INT NULL,

    breathline_phase     VARCHAR(32) NULL,
    field_coherence      VARCHAR(32) NULL,
    compass_rank         INT NULL,
    anchor_state         VARCHAR(32) NULL,
    sentiment_state      VARCHAR(32) NULL,
    fear_greed_value     INT NULL,
    sentiment_score      DECIMAL(10,6) NULL,

    notes                TEXT NULL,
    created_ts           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_compass_pred (prediction_ts_utc),
    KEY idx_compass_asset_pred (asset_id, prediction_ts_utc),
    CONSTRAINT fk_compass_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
);

-- Optional starter assets discussed in chat
INSERT INTO asset (symbol, name, sector, is_enabled, is_portfolio, is_core_sensor)
VALUES
('BTC', 'Bitcoin', 'Other', 1, 0, 1),
('ETH', 'Ethereum', 'L1', 1, 1, 1),
('SOL', 'Solana', 'L1', 1, 0, 1),
('ADA', 'Cardano', 'L1', 1, 0, 1)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    sector = VALUES(sector),
    is_enabled = VALUES(is_enabled),
    is_core_sensor = VALUES(is_core_sensor);
