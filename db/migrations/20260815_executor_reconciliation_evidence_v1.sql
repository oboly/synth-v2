-- MIGRATION_STATE=CREATED_NOT_APPLIED
-- PR2 shared reconciliation evidence and authoritative found-order resolution.
ALTER TABLE executor_execution_leg
 ADD COLUMN broker_raw_status VARCHAR(64) NULL AFTER broker_order_id,
 ADD COLUMN restatement_reason VARCHAR(128) NULL AFTER broker_raw_status,
 ADD COLUMN last_reconciled_ts_utc DATETIME(6) NULL AFTER restatement_reason;

DROP TRIGGER IF EXISTS trg_eel_immutable;
DELIMITER //
CREATE TRIGGER trg_eel_immutable BEFORE UPDATE ON executor_execution_leg FOR EACH ROW BEGIN
 IF NOT (OLD.executor_execution_handoff_id <=> NEW.executor_execution_handoff_id AND OLD.leg_index <=> NEW.leg_index AND OLD.trading_account_id <=> NEW.trading_account_id AND OLD.venue <=> NEW.venue AND OLD.market <=> NEW.market AND OLD.side <=> NEW.side AND OLD.client_order_id <=> NEW.client_order_id AND OLD.operator_id <=> NEW.operator_id AND OLD.price <=> NEW.price AND OLD.quantity <=> NEW.quantity) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor execution leg identity immutable'; END IF;
 IF NOT ((OLD.state='PREPARED' AND NEW.state='SUBMISSION_UNCERTAIN') OR (OLD.state='SUBMISSION_UNCERTAIN' AND NEW.state IN ('RECONCILIATION_REQUIRED','ACTIVE','PARTIALLY_FILLED','FILLED','CANCELED','EXPIRED','REJECTED','FAILED')) OR (OLD.state='RECONCILIATION_REQUIRED' AND NEW.state IN ('ACTIVE','PARTIALLY_FILLED','FILLED','CANCELED','EXPIRED','REJECTED')) OR (OLD.state='ACTIVE' AND NEW.state IN ('PARTIALLY_FILLED','FILLED','CANCELED','EXPIRED')) OR (OLD.state='PARTIALLY_FILLED' AND NEW.state IN ('FILLED','CANCELED','EXPIRED'))) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid executor leg state transition'; END IF;
END//
DELIMITER ;
