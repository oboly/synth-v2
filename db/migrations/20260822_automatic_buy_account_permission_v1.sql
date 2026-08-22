-- Issue #474: decision-gate-owned automatic BUY execution permission.
--
-- Canonical owner of `automatic_buy_execution_enabled` account evidence. This
-- is a general account-level opt-in for automatic BUY execution (applies to
-- both PAPER and LIVE account modes); it is wholly separate from
-- `automatic_buy_live_decision_gate_permission_v1`, which grants the
-- additional LIVE-only decision-gate permission required on top of this
-- general opt-in. This migration grants no executor authority, credential,
-- kill-switch, broker access, or order authority, and does not set
-- `trading_account.live_trading_enabled`. Migration artifact only; not
-- applied by this change.

CREATE TABLE IF NOT EXISTS automatic_buy_account_permission_v1 (
    automatic_buy_account_permission_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    execution_enabled TINYINT(1) NOT NULL DEFAULT 0,
    effective_from_ts_utc DATETIME(6) NOT NULL,
    effective_until_ts_utc DATETIME(6) NULL,
    permission_version VARCHAR(32) NOT NULL DEFAULT '1',
    source_provenance VARCHAR(128) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (automatic_buy_account_permission_id),
    UNIQUE KEY uq_automatic_buy_account_permission_account_binding (
        automatic_buy_account_permission_id, trading_account_id
    ),
    KEY ix_automatic_buy_account_permission_lookup (trading_account_id, effective_from_ts_utc),
    CONSTRAINT fk_automatic_buy_account_permission_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT chk_automatic_buy_account_permission_flag CHECK (execution_enabled IN (0, 1)),
    CONSTRAINT chk_automatic_buy_account_permission_window CHECK (
        effective_until_ts_utc IS NULL OR effective_until_ts_utc > effective_from_ts_utc
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only account-scoped automatic-BUY execution opt-in. No row means disabled; this is not LIVE or order authority.';

DELIMITER //
CREATE TRIGGER trg_automatic_buy_account_permission_v1_no_update
BEFORE UPDATE ON automatic_buy_account_permission_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic buy account permission is immutable; append a revocation fact instead';
END//
CREATE TRIGGER trg_automatic_buy_account_permission_v1_no_delete
BEFORE DELETE ON automatic_buy_account_permission_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic buy account permission is immutable; append a revocation fact instead';
END//
DELIMITER ;

CREATE TABLE IF NOT EXISTS automatic_buy_account_permission_revocation_v1 (
    automatic_buy_account_permission_revocation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    automatic_buy_account_permission_id BIGINT UNSIGNED NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    revocation_version VARCHAR(16) NOT NULL,
    effective_ts_utc DATETIME(6) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    reason VARCHAR(512) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (automatic_buy_account_permission_revocation_id),
    KEY ix_automatic_buy_account_permission_revocation_binding (
        automatic_buy_account_permission_id, trading_account_id
    ),
    KEY ix_automatic_buy_account_permission_revocation_lookup (
        automatic_buy_account_permission_id, effective_ts_utc
    ),
    KEY ix_automatic_buy_account_permission_revocation_account (
        trading_account_id, effective_ts_utc
    ),
    CONSTRAINT fk_automatic_buy_account_permission_revocation_binding
        FOREIGN KEY (automatic_buy_account_permission_id, trading_account_id)
        REFERENCES automatic_buy_account_permission_v1 (
            automatic_buy_account_permission_id, trading_account_id
        ),
    CONSTRAINT chk_automatic_buy_account_permission_revocation_text CHECK (
        CHAR_LENGTH(TRIM(actor)) > 0 AND CHAR_LENGTH(TRIM(reason)) > 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only revocation facts for automatic BUY account execution permission.';

DELIMITER //
CREATE TRIGGER trg_automatic_buy_account_permission_revocation_v1_no_update
BEFORE UPDATE ON automatic_buy_account_permission_revocation_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic buy account permission revocation facts are append-only';
END//
CREATE TRIGGER trg_automatic_buy_account_permission_revocation_v1_no_delete
BEFORE DELETE ON automatic_buy_account_permission_revocation_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic buy account permission revocation facts are append-only';
END//
DELIMITER ;
