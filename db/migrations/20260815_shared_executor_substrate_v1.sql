-- MIGRATION_STATE=CREATED_NOT_APPLIED
-- Shared executor substrate v1. Schema only; no broker, runtime, or live authority.
CREATE TABLE executor_execution_handoff (
 executor_execution_handoff_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
 plan_source VARCHAR(96) NOT NULL, plan_reference_id VARCHAR(128) NOT NULL,
 plan_content_hash CHAR(64) NOT NULL, trading_account_id BIGINT UNSIGNED NOT NULL,
 venue VARCHAR(32) NOT NULL, market VARCHAR(64) NOT NULL, side VARCHAR(4) NOT NULL,
 executor_mode VARCHAR(16) NOT NULL COMMENT 'DRY_RUN | PAPER | LIVE; application denies LIVE',
 executor_identity VARCHAR(128) NOT NULL, runtime_owner VARCHAR(64) NOT NULL,
 executor_credential_binding_id BIGINT UNSIGNED NOT NULL,
 created_ts_utc DATETIME(6) NOT NULL,
 PRIMARY KEY (executor_execution_handoff_id), UNIQUE KEY uq_eeh_plan_ref (plan_source,plan_reference_id),
 CONSTRAINT fk_eeh_binding FOREIGN KEY (executor_credential_binding_id) REFERENCES executor_credential_binding(executor_credential_binding_id),
 CONSTRAINT chk_eeh_side CHECK (side IN ('BUY','SELL')),
 CONSTRAINT chk_eeh_mode CHECK (executor_mode IN ('DRY_RUN','PAPER','LIVE'))
) ENGINE=InnoDB;
CREATE TABLE executor_execution_leg (
 executor_execution_leg_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
 executor_execution_handoff_id BIGINT UNSIGNED NOT NULL, leg_index INT UNSIGNED NOT NULL,
 trading_account_id BIGINT UNSIGNED NOT NULL, venue VARCHAR(32) NOT NULL, market VARCHAR(64) NOT NULL,
 side VARCHAR(4) NOT NULL, client_order_id CHAR(36) NOT NULL,
 operator_id BIGINT UNSIGNED NOT NULL,
 price DECIMAL(36,18) NOT NULL, quantity DECIMAL(36,18) NOT NULL,
 state VARCHAR(32) NOT NULL DEFAULT 'PREPARED', broker_order_id VARCHAR(128) NULL,
 created_ts_utc DATETIME(6) NOT NULL, updated_ts_utc DATETIME(6) NULL,
 PRIMARY KEY (executor_execution_leg_id), UNIQUE KEY uq_eel_handoff_leg (executor_execution_handoff_id,leg_index), UNIQUE KEY uq_eel_client_order_id(client_order_id),
 CONSTRAINT fk_eel_handoff FOREIGN KEY (executor_execution_handoff_id) REFERENCES executor_execution_handoff(executor_execution_handoff_id),
 CONSTRAINT chk_eel_side CHECK (side IN ('BUY','SELL')),
 CONSTRAINT chk_eel_state CHECK (state IN ('PREPARED','SUBMISSION_UNCERTAIN','RECONCILIATION_REQUIRED','ACTIVE','PARTIALLY_FILLED','FILLED','CANCELED','EXPIRED','REJECTED','FAILED')),
 CONSTRAINT chk_eel_positive CHECK (price > 0 AND quantity > 0)
) ENGINE=InnoDB;
DELIMITER //
CREATE TRIGGER trg_eeh_no_delete BEFORE DELETE ON executor_execution_handoff FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor handoffs cannot be deleted'; END//
CREATE TRIGGER trg_eeh_immutable BEFORE UPDATE ON executor_execution_handoff FOR EACH ROW BEGIN
 IF NOT (OLD.plan_source <=> NEW.plan_source AND OLD.plan_reference_id <=> NEW.plan_reference_id AND OLD.plan_content_hash <=> NEW.plan_content_hash AND OLD.trading_account_id <=> NEW.trading_account_id AND OLD.venue <=> NEW.venue AND OLD.market <=> NEW.market AND OLD.side <=> NEW.side AND OLD.executor_mode <=> NEW.executor_mode AND OLD.executor_identity <=> NEW.executor_identity AND OLD.runtime_owner <=> NEW.runtime_owner AND OLD.executor_credential_binding_id <=> NEW.executor_credential_binding_id) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor handoff identity immutable'; END IF;
END//
CREATE TRIGGER trg_eel_no_delete BEFORE DELETE ON executor_execution_leg FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor execution legs cannot be deleted'; END//
CREATE TRIGGER trg_eel_immutable BEFORE UPDATE ON executor_execution_leg FOR EACH ROW BEGIN
 IF NOT (OLD.executor_execution_handoff_id <=> NEW.executor_execution_handoff_id AND OLD.leg_index <=> NEW.leg_index AND OLD.trading_account_id <=> NEW.trading_account_id AND OLD.venue <=> NEW.venue AND OLD.market <=> NEW.market AND OLD.side <=> NEW.side AND OLD.client_order_id <=> NEW.client_order_id AND OLD.operator_id <=> NEW.operator_id AND OLD.price <=> NEW.price AND OLD.quantity <=> NEW.quantity) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor execution leg identity immutable'; END IF;
 IF NOT ((OLD.state='PREPARED' AND NEW.state='SUBMISSION_UNCERTAIN') OR (OLD.state='SUBMISSION_UNCERTAIN' AND NEW.state IN ('RECONCILIATION_REQUIRED','ACTIVE','PARTIALLY_FILLED','FILLED','CANCELED','EXPIRED','REJECTED','FAILED')) OR (OLD.state='ACTIVE' AND NEW.state IN ('PARTIALLY_FILLED','FILLED','CANCELED','EXPIRED')) OR (OLD.state='PARTIALLY_FILLED' AND NEW.state IN ('FILLED','CANCELED','EXPIRED'))) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='invalid executor leg state transition'; END IF;
END//
DELIMITER ;
