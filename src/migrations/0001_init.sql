CREATE TABLE IF NOT EXISTS asset (
  asset_id        INT AUTO_INCREMENT PRIMARY KEY,
  symbol          VARCHAR(32) NOT NULL UNIQUE,
  quote_ccy       VARCHAR(8)  NOT NULL DEFAULT 'EUR',
  is_active       TINYINT     NOT NULL DEFAULT 1,
  created_ts      DATETIME(6) NOT NULL,
  updated_ts      DATETIME(6) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS candle (
  candle_id       BIGINT AUTO_INCREMENT PRIMARY KEY,
  asset_id        INT NOT NULL,
  tf              VARCHAR(16) NOT NULL,
  start_ts        DATETIME(6) NOT NULL,
  end_ts          DATETIME(6) NOT NULL,
  open            DECIMAL(28, 12) NOT NULL,
  high            DECIMAL(28, 12) NOT NULL,
  low             DECIMAL(28, 12) NOT NULL,
  close           DECIMAL(28, 12) NOT NULL,
  volume          DECIMAL(28, 12) NOT NULL,
  source          VARCHAR(32) NOT NULL DEFAULT 'bitvavo',
  ingest_ts       DATETIME(6) NOT NULL,
  UNIQUE KEY uq_candle (asset_id, tf, start_ts),
  KEY ix_candle_asset_tf_end (asset_id, tf, end_ts),
  CONSTRAINT fk_candle_asset FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS candle_feat (
  candle_feat_id  BIGINT AUTO_INCREMENT PRIMARY KEY,
  candle_id       BIGINT NOT NULL,
  feat_key        VARCHAR(64) NOT NULL,
  period          INT NULL,
  src             VARCHAR(16) NULL,
  params_json     JSON NULL,
  feat_value      DOUBLE NOT NULL,
  feat_ver        VARCHAR(32) NOT NULL DEFAULT 'v1',
  calc_ts         DATETIME(6) NOT NULL,
  provenance      VARCHAR(64) NOT NULL DEFAULT 'synth',
  UNIQUE KEY uq_feat (candle_id, feat_key, period, src, feat_ver),
  KEY ix_feat_lookup (feat_key, period, src),
  CONSTRAINT fk_feat_candle FOREIGN KEY (candle_id) REFERENCES candle(candle_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS manual_zone (
  zone_id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  asset_id        INT NOT NULL,
  side            ENUM('BUY','SELL') NOT NULL,
  low             DECIMAL(28, 12) NOT NULL,
  high            DECIMAL(28, 12) NOT NULL,
  invalidation    DECIMAL(28, 12) NULL,
  bias            DOUBLE NOT NULL DEFAULT 0.0,
  priority        INT NOT NULL DEFAULT 100,
  start_ts        DATETIME(6) NOT NULL,
  end_ts          DATETIME(6) NOT NULL,
  note            VARCHAR(255) NULL,
  created_ts      DATETIME(6) NOT NULL,
  updated_ts      DATETIME(6) NOT NULL,
  KEY ix_zone_active (asset_id, side, start_ts, end_ts),
  CONSTRAINT fk_zone_asset FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS decision_log (
  decision_id     BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id          VARCHAR(64) NOT NULL,
  ts              DATETIME(6) NOT NULL,
  asset_id        INT NOT NULL,
  tf              VARCHAR(16) NOT NULL,
  candle_start_ts DATETIME(6) NULL,
  strategy_key    VARCHAR(64) NOT NULL,
  proposed_side   ENUM('BUY','SELL','HOLD') NOT NULL,
  raw_score       DOUBLE NOT NULL,
  zone_bias       DOUBLE NOT NULL DEFAULT 0.0,
  other_bias      DOUBLE NOT NULL DEFAULT 0.0,
  final_score     DOUBLE NOT NULL,
  risk_blocked    TINYINT NOT NULL DEFAULT 0,
  risk_reason     VARCHAR(255) NULL,
  action_taken    ENUM('NONE','ORDER_PLACED','ORDER_SKIPPED') NOT NULL DEFAULT 'NONE',
  action_reason   VARCHAR(255) NULL,
  meta_json       JSON NULL,
  KEY ix_decision_run (run_id, ts),
  KEY ix_decision_asset_ts (asset_id, ts),
  CONSTRAINT fk_decision_asset FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
) ENGINE=InnoDB;

CREATE OR REPLACE VIEW v_candle_feat_core AS
SELECT
  c.asset_id,
  a.symbol,
  c.tf,
  c.start_ts,
  c.end_ts,
  c.open, c.high, c.low, c.close, c.volume,
  MAX(CASE WHEN f.feat_key='ema' AND f.period=20 AND f.src='close' THEN f.feat_value END) AS ema_20,
  MAX(CASE WHEN f.feat_key='sma' AND f.period=20 AND f.src='close' THEN f.feat_value END) AS sma_20,
  MAX(CASE WHEN f.feat_key='rsi' AND f.period=14 AND f.src='close' THEN f.feat_value END) AS rsi_14
FROM candle c
JOIN asset a ON a.asset_id = c.asset_id
LEFT JOIN candle_feat f ON f.candle_id = c.candle_id
GROUP BY
  c.asset_id, a.symbol, c.tf, c.start_ts, c.end_ts,
  c.open, c.high, c.low, c.close, c.volume;