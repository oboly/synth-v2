-- MIGRATION_STATE=CREATED_NOT_APPLIED
-- Persisted immutable plan intent and multi-worker consumer claims for #206.
CREATE TABLE executor_execution_handoff_plan_leg (
 executor_execution_handoff_id BIGINT UNSIGNED NOT NULL, leg_index INT UNSIGNED NOT NULL,
 trading_account_id BIGINT UNSIGNED NOT NULL, venue VARCHAR(32) NOT NULL, market VARCHAR(64) NOT NULL,
 side VARCHAR(4) NOT NULL, price DECIMAL(36,18) NOT NULL, quantity DECIMAL(36,18) NOT NULL,
 created_ts_utc DATETIME(6) NOT NULL,
 PRIMARY KEY (executor_execution_handoff_id, leg_index),
 CONSTRAINT fk_eehpl_handoff FOREIGN KEY (executor_execution_handoff_id) REFERENCES executor_execution_handoff(executor_execution_handoff_id),
 CONSTRAINT chk_eehpl_side CHECK (side IN ('BUY','SELL')),
 CONSTRAINT chk_eehpl_positive CHECK (price > 0 AND quantity > 0)
) ENGINE=InnoDB;
CREATE TABLE executor_execution_handoff_consumption (
 executor_execution_handoff_id BIGINT UNSIGNED NOT NULL, state VARCHAR(16) NOT NULL,
 claim_token CHAR(36) NULL, claimed_by VARCHAR(128) NULL, claim_expires_ts_utc DATETIME(6) NULL,
 created_ts_utc DATETIME(6) NOT NULL, updated_ts_utc DATETIME(6) NULL,
 PRIMARY KEY (executor_execution_handoff_id), KEY ix_eehc_discovery (state, executor_execution_handoff_id),
 CONSTRAINT fk_eehc_handoff FOREIGN KEY (executor_execution_handoff_id) REFERENCES executor_execution_handoff(executor_execution_handoff_id),
 CONSTRAINT chk_eehc_state CHECK (state IN ('PENDING','CLAIMED','COMPLETED'))
) ENGINE=InnoDB;
DELIMITER //
CREATE TRIGGER trg_eehpl_no_delete BEFORE DELETE ON executor_execution_handoff_plan_leg FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor handoff plan legs cannot be deleted'; END//
CREATE TRIGGER trg_eehpl_immutable BEFORE UPDATE ON executor_execution_handoff_plan_leg FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor handoff plan legs are immutable'; END//
CREATE TRIGGER trg_eehc_no_delete BEFORE DELETE ON executor_execution_handoff_consumption FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor handoff consumption cannot be deleted'; END//
DELIMITER ;
