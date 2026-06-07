-- Migration: app_profile_trading_account_link_v1
-- Idempotent: safe to re-run.
-- Purpose: explicit multi-account-capable link between app_profile and trading_account.
--          Owned by the account layer. No credentials stored here.
-- Prerequisite: 20260605_website_registration_foundation_v1.sql (app_profile table)

CREATE TABLE IF NOT EXISTS app_profile_trading_account_link (
    link_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    app_profile_id     BIGINT UNSIGNED NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    link_status        VARCHAR(32)     NOT NULL DEFAULT 'ACTIVE'
        COMMENT 'ACTIVE | REVOKED',
    is_primary         TINYINT(1)      NOT NULL DEFAULT 0
        COMMENT '1 = primary account for landing and dashboard resolution',
    created_ts_utc     DATETIME        NOT NULL,
    updated_ts_utc     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (link_id),
    UNIQUE KEY uq_profile_account (app_profile_id, trading_account_id),
    KEY idx_profile_active_primary (app_profile_id, link_status, is_primary),
    CONSTRAINT fk_aptl_profile
        FOREIGN KEY (app_profile_id)     REFERENCES app_profile (app_profile_id),
    CONSTRAINT fk_aptl_trading_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT chk_aptl_link_status
        CHECK (link_status IN ('ACTIVE', 'REVOKED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Explicit app_profile to trading_account linkage. No credentials stored.';
