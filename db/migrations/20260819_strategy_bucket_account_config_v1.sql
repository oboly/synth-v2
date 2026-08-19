-- Issue #279: durable, versioned, account-scoped strategy-bucket
-- activation and risk/allocation configuration. decision_gate is the sole
-- owner. Migration artifact only; do not apply from this change.
--
-- strategy_bucket_id is the canonical strategy-bucket identity (e.g.
-- SHORT_TERM_ROTATION, MEDIUM_SWING, BREATH_CURVE_RESEARCH). Bucket
-- definition/validation is owned upstream (#232); this table only stores
-- an account's activation/risk configuration for a bucket it already
-- refers to by id.
--
-- Shape mirrors db/migrations/20260817_account_protection_policy_config_v1.sql:
-- append-only, effective-windowed config rows plus an immutable revocation
-- fact table. No UPDATE/DELETE on either table; superseding or ending an
-- open-ended row is expressed exclusively via a revocation fact.

CREATE TABLE IF NOT EXISTS strategy_bucket_account_config_v1 (
    strategy_bucket_account_config_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    strategy_bucket_id VARCHAR(64) NOT NULL,
    config_version VARCHAR(16) NOT NULL,
    is_enabled TINYINT(1) NOT NULL,
    risk_profile VARCHAR(64) NOT NULL,
    max_position_amount_eur DECIMAL(30,18) NULL,
    max_bucket_amount_eur DECIMAL(30,18) NULL,
    max_asset_exposure_pct DECIMAL(9,6) NULL,
    max_open_positions INT UNSIGNED NULL,
    allow_new_entries TINYINT(1) NOT NULL,
    allow_reduce_reviews TINYINT(1) NOT NULL,
    effective_from_ts_utc DATETIME(6) NOT NULL,
    effective_until_ts_utc DATETIME(6) NULL,
    source_provenance VARCHAR(128) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (strategy_bucket_account_config_id),
    UNIQUE KEY uq_strategy_bucket_account_config_account_binding (
        strategy_bucket_account_config_id, trading_account_id
    ),
    KEY ix_strategy_bucket_account_config_lookup (
        trading_account_id, strategy_bucket_id, effective_from_ts_utc
    ),
    CONSTRAINT fk_strategy_bucket_account_config_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT chk_strategy_bucket_account_config_window CHECK (
        effective_until_ts_utc IS NULL OR effective_until_ts_utc > effective_from_ts_utc
    ),
    CONSTRAINT chk_strategy_bucket_account_config_position_amount CHECK (
        max_position_amount_eur IS NULL OR max_position_amount_eur > 0
    ),
    CONSTRAINT chk_strategy_bucket_account_config_bucket_amount CHECK (
        max_bucket_amount_eur IS NULL OR max_bucket_amount_eur > 0
    ),
    CONSTRAINT chk_strategy_bucket_account_config_asset_exposure_pct CHECK (
        max_asset_exposure_pct IS NULL OR (max_asset_exposure_pct > 0 AND max_asset_exposure_pct <= 100)
    ),
    CONSTRAINT chk_strategy_bucket_account_config_open_positions CHECK (
        max_open_positions IS NULL OR max_open_positions > 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only account-scoped strategy-bucket activation/risk configuration. No effective row means the bucket is unresolved and #279 fails closed. decision_gate-owned only.';

-- Strictly append-only: no UPDATE, no DELETE, ever.
DELIMITER //
CREATE TRIGGER trg_strategy_bucket_account_config_v1_no_update
BEFORE UPDATE ON strategy_bucket_account_config_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'strategy bucket account config is immutable; append a revocation fact instead';
END//
CREATE TRIGGER trg_strategy_bucket_account_config_v1_no_delete
BEFORE DELETE ON strategy_bucket_account_config_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'strategy bucket account config is immutable; append a revocation fact instead';
END//
DELIMITER ;

-- Immutable, append-only revocation/supersession lifecycle facts. Multiple
-- revocation facts per config row are permitted by design (see the #318
-- account_protection_policy_config_revocation_v1 precedent this mirrors).
-- trading_account_id is denormalized from the referenced config row; the
-- composite FK below binds (config_id, trading_account_id) against the
-- config table's own matching unique key so MariaDB itself rejects a
-- structurally corrupt cross-account revocation row.
CREATE TABLE IF NOT EXISTS strategy_bucket_account_config_revocation_v1 (
    strategy_bucket_account_config_revocation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    strategy_bucket_account_config_id BIGINT UNSIGNED NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    revocation_version VARCHAR(16) NOT NULL,
    effective_ts_utc DATETIME(6) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    reason VARCHAR(512) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (strategy_bucket_account_config_revocation_id),
    KEY ix_strategy_bucket_account_config_revocation_binding (
        strategy_bucket_account_config_id, trading_account_id
    ),
    KEY ix_strategy_bucket_account_config_revocation_lookup (
        strategy_bucket_account_config_id, effective_ts_utc
    ),
    KEY ix_strategy_bucket_account_config_revocation_account (
        trading_account_id, effective_ts_utc
    ),
    CONSTRAINT fk_strategy_bucket_account_config_revocation_config_account
        FOREIGN KEY (strategy_bucket_account_config_id, trading_account_id)
        REFERENCES strategy_bucket_account_config_v1 (
            strategy_bucket_account_config_id, trading_account_id
        ),
    CONSTRAINT chk_strategy_bucket_account_config_revocation_text CHECK (
        CHAR_LENGTH(TRIM(actor)) > 0 AND CHAR_LENGTH(TRIM(reason)) > 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Immutable, append-only revocation/supersession facts for strategy_bucket_account_config_v1. Never updated or deleted.';

DELIMITER //
CREATE TRIGGER trg_strategy_bucket_account_config_revocation_v1_no_update
BEFORE UPDATE ON strategy_bucket_account_config_revocation_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'strategy bucket account config revocation facts are append-only';
END//
CREATE TRIGGER trg_strategy_bucket_account_config_revocation_v1_no_delete
BEFORE DELETE ON strategy_bucket_account_config_revocation_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'strategy bucket account config revocation facts are append-only';
END//
DELIMITER ;
