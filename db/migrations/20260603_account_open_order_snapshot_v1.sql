-- Migration: account_open_order_snapshot_v1
-- Boundary: per-account snapshot only · no broker writes · no order submission · no side restriction
-- Purpose: store all open orders per account snapshot, not limited to SELL side.
--          Complements trading_account_balance_snapshot for the wallet refresh layer.
-- Non-goals: no order placement · no cancellation · no decision_gate · no execution_planner

CREATE TABLE IF NOT EXISTS account_open_order_snapshot (
    snapshot_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    snapshot_ts_utc     DATETIME     NOT NULL,
    trading_account_id  BIGINT UNSIGNED NOT NULL,
    venue               VARCHAR(32)  NOT NULL,
    market              VARCHAR(32)  NOT NULL,

    broker_order_id     VARCHAR(128) NOT NULL,
    client_order_id     VARCHAR(128) DEFAULT NULL,
    side                VARCHAR(8)   NOT NULL COMMENT 'BUY | SELL',
    order_type          VARCHAR(32)  NOT NULL,
    limit_price         DECIMAL(20,10) DEFAULT NULL,
    quantity            DECIMAL(20,10) NOT NULL,
    filled_quantity     DECIMAL(20,10) NOT NULL DEFAULT 0,
    remaining_quantity  DECIMAL(20,10) NOT NULL,
    broker_status       VARCHAR(32)  NOT NULL,

    created_ts  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_order_snapshot (trading_account_id, snapshot_ts_utc, broker_order_id),
    KEY idx_order_snapshot_market (trading_account_id, venue, market),
    CONSTRAINT fk_order_snapshot_ta
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='All open orders per account per snapshot. No side restriction. Read-only from broker.';
