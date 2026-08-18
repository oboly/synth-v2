-- Issue #392 Phase 6 blocker C / Issue #318: durable, versioned,
-- account-scoped account-protection policy configuration, plus protection
-- provenance columns on the existing Phase 4B automatic-exit audit table.
-- Migration artifact only; do not apply from this change.

CREATE TABLE IF NOT EXISTS account_protection_policy_config_v1 (
    account_protection_policy_config_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    config_version VARCHAR(16) NOT NULL,
    configuration_version VARCHAR(128) NOT NULL,
    max_account_drawdown DECIMAL(30,18) NULL,
    max_daily_realized_loss DECIMAL(30,18) NULL,
    max_repeated_stoploss_streak INT UNSIGNED NULL,
    max_metric_age_seconds INT UNSIGNED NOT NULL DEFAULT 900,
    effective_from_ts_utc DATETIME(6) NOT NULL,
    effective_until_ts_utc DATETIME(6) NULL,
    source_provenance VARCHAR(128) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (account_protection_policy_config_id),
    KEY ix_account_protection_policy_config_lookup (trading_account_id, effective_from_ts_utc),
    CONSTRAINT fk_account_protection_policy_config_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT chk_account_protection_policy_config_window CHECK (
        effective_until_ts_utc IS NULL OR effective_until_ts_utc > effective_from_ts_utc
    ),
    CONSTRAINT chk_account_protection_policy_config_drawdown CHECK (
        max_account_drawdown IS NULL OR max_account_drawdown > 0
    ),
    CONSTRAINT chk_account_protection_policy_config_daily_loss CHECK (
        max_daily_realized_loss IS NULL OR max_daily_realized_loss > 0
    ),
    CONSTRAINT chk_account_protection_policy_config_streak CHECK (
        max_repeated_stoploss_streak IS NULL OR max_repeated_stoploss_streak > 0
    ),
    CONSTRAINT chk_account_protection_policy_config_metric_age CHECK (max_metric_age_seconds >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only account-scoped account-protection thresholds. No effective row means protection configuration is unresolved and #392 fails closed.';

-- Strictly append-only: no UPDATE, no DELETE, ever. A config row's window is
-- fixed for its lifetime. Superseding or ending an open-ended
-- (effective_until_ts_utc IS NULL) row is expressed exclusively through an
-- immutable revocation fact in account_protection_policy_config_revocation_v1
-- below, never by mutating the config row itself.
DELIMITER //
CREATE TRIGGER trg_account_protection_policy_config_v1_no_update
BEFORE UPDATE ON account_protection_policy_config_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'account protection policy config is immutable; append a revocation fact instead';
END//
CREATE TRIGGER trg_account_protection_policy_config_v1_no_delete
BEFORE DELETE ON account_protection_policy_config_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'account protection policy config is immutable; append a revocation fact instead';
END//
DELIMITER ;

-- Immutable, append-only revocation/supersession lifecycle facts for
-- account_protection_policy_config_v1. Multiple revocation facts per config
-- row are permitted by design (e.g. an earlier scheduled future revocation
-- must never block a later immediate one from also being recorded); the
-- resolver treats a config row as revoked at time T if ANY of its
-- revocation facts has effective_ts_utc <= T. trading_account_id is
-- denormalized from the referenced config row so the resolver can detect a
-- corrupt/conflicting cross-account reference without a join.
CREATE TABLE IF NOT EXISTS account_protection_policy_config_revocation_v1 (
    account_protection_policy_config_revocation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    account_protection_policy_config_id BIGINT UNSIGNED NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    revocation_version VARCHAR(16) NOT NULL,
    effective_ts_utc DATETIME(6) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    reason VARCHAR(512) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (account_protection_policy_config_revocation_id),
    KEY ix_account_protection_policy_config_revocation_lookup (
        account_protection_policy_config_id, effective_ts_utc
    ),
    KEY ix_account_protection_policy_config_revocation_account (
        trading_account_id, effective_ts_utc
    ),
    CONSTRAINT fk_account_protection_policy_config_revocation_config
        FOREIGN KEY (account_protection_policy_config_id)
        REFERENCES account_protection_policy_config_v1 (account_protection_policy_config_id),
    CONSTRAINT fk_account_protection_policy_config_revocation_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT chk_account_protection_policy_config_revocation_text CHECK (
        CHAR_LENGTH(TRIM(actor)) > 0 AND CHAR_LENGTH(TRIM(reason)) > 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Immutable, append-only revocation/supersession facts for account_protection_policy_config_v1. Never updated or deleted.';

DELIMITER //
CREATE TRIGGER trg_account_protection_policy_config_revocation_v1_no_update
BEFORE UPDATE ON account_protection_policy_config_revocation_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'account protection policy config revocation facts are append-only';
END//
CREATE TRIGGER trg_account_protection_policy_config_revocation_v1_no_delete
BEFORE DELETE ON account_protection_policy_config_revocation_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'account protection policy config revocation facts are append-only';
END//
DELIMITER ;

-- Preserve #318 protection provenance on the append-only Phase 4B audit
-- table. gate_reason_code already carries the protection reason code when a
-- protection denies (account_protection_evaluation.reason_code overwrites
-- the gate's own reason_code on BLOCKED), but nothing previously recorded
-- which protection evaluated and permitted an APPROVED decision. These
-- columns are additional review/audit evidence only, never an executor
-- input.
ALTER TABLE automatic_exit_evaluation_audit_v1
    ADD COLUMN protection_code VARCHAR(64) NULL AFTER gate_reason_code,
    ADD COLUMN protection_reason_code VARCHAR(128) NULL AFTER protection_code;
