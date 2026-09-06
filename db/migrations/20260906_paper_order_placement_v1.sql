-- MIGRATION_STATE=CREATED_NOT_APPLIED
-- Issue #753 B5.5 review fix (PR #776): durable PAPER order-placement
-- identity so find_order_by_client_order_id can recover an already
-- acknowledged ACTIVE/REJECTED PAPER order after a crash between broker ack
-- and executor_execution_leg persistence. Schema only; no broker, runtime,
-- or live authority.
CREATE TABLE executor_paper_order_placement (
 executor_paper_order_placement_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
 market VARCHAR(64) NOT NULL, client_order_id CHAR(36) NOT NULL,
 side VARCHAR(4) NOT NULL, price DECIMAL(36,18) NOT NULL, quantity DECIMAL(36,18) NOT NULL,
 state VARCHAR(16) NOT NULL, broker_order_id VARCHAR(128) NULL, broker_raw_status VARCHAR(64) NOT NULL,
 created_ts_utc DATETIME(6) NOT NULL,
 PRIMARY KEY (executor_paper_order_placement_id),
 UNIQUE KEY uq_epop_market_client_order_id (market, client_order_id),
 CONSTRAINT chk_epop_side CHECK (side IN ('BUY','SELL')),
 CONSTRAINT chk_epop_state CHECK (state IN ('ACTIVE','REJECTED')),
 CONSTRAINT chk_epop_positive CHECK (price > 0 AND quantity > 0)
) ENGINE=InnoDB;
DELIMITER //
CREATE TRIGGER trg_epop_no_delete BEFORE DELETE ON executor_paper_order_placement FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='paper order placements cannot be deleted'; END//
CREATE TRIGGER trg_epop_immutable BEFORE UPDATE ON executor_paper_order_placement FOR EACH ROW BEGIN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='paper order placement identity immutable';
END//
DELIMITER ;
