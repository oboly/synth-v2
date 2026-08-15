-- Issue #318: immutable decision-gate account-protection lifecycle facts.
-- Migration artifact only; do not apply from this change.

CREATE TABLE IF NOT EXISTS account_protection_lock_fact_v1 (
    account_protection_lock_fact_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    lifecycle_id CHAR(64) NOT NULL,
    event_id CHAR(64) NOT NULL,
    protection_code VARCHAR(64) NOT NULL,
    protection_version VARCHAR(16) NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    scope_type VARCHAR(16) NOT NULL,
    scope_id VARCHAR(128) NOT NULL,
    observed_from_ts_utc DATETIME(6) NOT NULL,
    observed_to_ts_utc DATETIME(6) NOT NULL,
    triggered_ts_utc DATETIME(6) NOT NULL,
    expires_ts_utc DATETIME(6) NULL,
    reason_code VARCHAR(128) NOT NULL,
    evidence_refs_json JSON NOT NULL,
    configuration_version VARCHAR(128) NOT NULL,
    lock_state VARCHAR(32) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (account_protection_lock_fact_id),
    UNIQUE KEY uq_account_protection_lock_fact_event (event_id),
    KEY ix_account_protection_lock_fact_account (
        trading_account_id, triggered_ts_utc, account_protection_lock_fact_id
    ),
    KEY ix_account_protection_lock_fact_lifecycle (
        lifecycle_id, triggered_ts_utc, account_protection_lock_fact_id
    ),
    CONSTRAINT fk_account_protection_lock_fact_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT chk_account_protection_lock_fact_window
        CHECK (observed_to_ts_utc > observed_from_ts_utc),
    CONSTRAINT chk_account_protection_lock_fact_expiry
        CHECK (expires_ts_utc IS NULL OR expires_ts_utc > triggered_ts_utc),
    CONSTRAINT chk_account_protection_lock_fact_state
        CHECK (lock_state IN ('ACTIVE', 'EXPIRED', 'RECOVERED', 'MANUALLY_CLEARED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only decision-gate protection facts; recovery and unlock append new lifecycle events.';

DELIMITER //
CREATE TRIGGER trg_account_protection_lock_fact_v1_no_update
BEFORE UPDATE ON account_protection_lock_fact_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'account protection facts are append-only';
END//
CREATE TRIGGER trg_account_protection_lock_fact_v1_no_delete
BEFORE DELETE ON account_protection_lock_fact_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'account protection facts are append-only';
END//
DELIMITER ;
