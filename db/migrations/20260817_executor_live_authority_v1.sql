-- MIGRATION_STATE=CREATED_NOT_APPLIED
-- Executor operational LIVE authority and global kill switch. Schema only.
-- No grants/events are seeded; no runtime or broker path is activated.

CREATE TABLE executor_live_authority_grant (
    executor_live_authority_grant_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    side VARCHAR(4) NOT NULL,
    market VARCHAR(64) NULL COMMENT 'NULL grants wildcard market scope only',
    executor_identity VARCHAR(128) NOT NULL,
    runtime_owner VARCHAR(64) NOT NULL,
    effective_from_ts_utc DATETIME(6) NOT NULL,
    effective_until_ts_utc DATETIME(6) NOT NULL,
    authorized_by VARCHAR(128) NOT NULL,
    authorization_reason VARCHAR(512) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (executor_live_authority_grant_id),
    KEY ix_elag_exact_resolution (
        trading_account_id, venue, side, market, executor_identity,
        runtime_owner, effective_from_ts_utc, effective_until_ts_utc
    ),
    CONSTRAINT fk_elag_trading_account FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT chk_elag_side CHECK (side IN ('BUY','SELL')),
    CONSTRAINT chk_elag_finite_window CHECK (
        effective_until_ts_utc > effective_from_ts_utc
        AND effective_until_ts_utc <= effective_from_ts_utc + INTERVAL 7 DAY
    ),
    CONSTRAINT chk_elag_required_text CHECK (
        CHAR_LENGTH(TRIM(venue)) > 0
        AND (market IS NULL OR CHAR_LENGTH(TRIM(market)) > 0)
        AND CHAR_LENGTH(TRIM(executor_identity)) > 0
        AND CHAR_LENGTH(TRIM(runtime_owner)) > 0
        AND CHAR_LENGTH(TRIM(authorized_by)) > 0
        AND CHAR_LENGTH(TRIM(authorization_reason)) > 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE executor_live_authority_revocation (
    executor_live_authority_revocation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    executor_live_authority_grant_id BIGINT UNSIGNED NOT NULL,
    revoked_ts_utc DATETIME(6) NOT NULL,
    revoked_by VARCHAR(128) NOT NULL,
    revocation_reason VARCHAR(512) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (executor_live_authority_revocation_id),
    UNIQUE KEY uq_elar_one_per_grant (executor_live_authority_grant_id),
    KEY ix_elar_effective (executor_live_authority_grant_id, revoked_ts_utc),
    CONSTRAINT fk_elar_grant FOREIGN KEY (executor_live_authority_grant_id)
        REFERENCES executor_live_authority_grant (executor_live_authority_grant_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT chk_elar_required_text CHECK (
        CHAR_LENGTH(TRIM(revoked_by)) > 0
        AND CHAR_LENGTH(TRIM(revocation_reason)) > 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE executor_kill_switch_event (
    executor_kill_switch_event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    state VARCHAR(16) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    reason VARCHAR(512) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL,
    PRIMARY KEY (executor_kill_switch_event_id),
    CONSTRAINT chk_ekse_state CHECK (state IN ('ENGAGED','DISENGAGED')),
    CONSTRAINT chk_ekse_required_text CHECK (
        CHAR_LENGTH(TRIM(actor)) > 0 AND CHAR_LENGTH(TRIM(reason)) > 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DELIMITER //
CREATE TRIGGER trg_elag_no_update BEFORE UPDATE ON executor_live_authority_grant
FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor LIVE authority grants are immutable'; END//
CREATE TRIGGER trg_elag_no_delete BEFORE DELETE ON executor_live_authority_grant
FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor LIVE authority grants cannot be deleted'; END//
CREATE TRIGGER trg_elar_no_update BEFORE UPDATE ON executor_live_authority_revocation
FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor LIVE authority revocations are immutable'; END//
CREATE TRIGGER trg_elar_no_delete BEFORE DELETE ON executor_live_authority_revocation
FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor LIVE authority revocations cannot be deleted'; END//
CREATE TRIGGER trg_ekse_no_update BEFORE UPDATE ON executor_kill_switch_event
FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor kill-switch events are immutable'; END//
CREATE TRIGGER trg_ekse_no_delete BEFORE DELETE ON executor_kill_switch_event
FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor kill-switch events cannot be deleted'; END//
DELIMITER ;
