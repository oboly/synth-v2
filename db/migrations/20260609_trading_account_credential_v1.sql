-- Migration: trading_account_credential_v1
-- Idempotent: safe to re-run.
-- Purpose: encrypted exchange API credential storage for account provisioning.
--          One row per active credential per (trading_account, venue).
--          No plaintext API key or secret columns.
--          One authenticated encrypted envelope per row.
-- Prerequisite: trading_account table must exist.

-- Deduplication and status enforcement are at the application layer.
-- The DB enforces only canonical status/validation values via CHECK constraints.

CREATE TABLE IF NOT EXISTS trading_account_credential (
    trading_account_credential_id BIGINT UNSIGNED      NOT NULL AUTO_INCREMENT,
    trading_account_id            BIGINT UNSIGNED      NOT NULL,
    venue                         VARCHAR(32)          NOT NULL,
    credential_kind               VARCHAR(32)          NOT NULL DEFAULT 'API_KEY_SECRET'
        COMMENT 'Kind of credential stored: API_KEY_SECRET',
    encrypted_envelope            MEDIUMTEXT           NOT NULL
        COMMENT 'JSON AESGCM-256 envelope. No plaintext credentials.',
    encryption_algorithm          VARCHAR(32)          NOT NULL DEFAULT 'AESGCM-256',
    key_version                   VARCHAR(16)          NOT NULL
        COMMENT 'Master key version prefix, e.g. v1',
    credential_fingerprint        CHAR(64)             NOT NULL
        COMMENT 'HMAC-SHA256 fingerprint of venue+api_key. Deterministic. No plaintext.',
    credential_status             VARCHAR(16)          NOT NULL DEFAULT 'ACTIVE'
        COMMENT 'ACTIVE | REVOKED | ROTATED | INVALID',
    validation_state              VARCHAR(32)          NOT NULL DEFAULT 'UNVALIDATED'
        COMMENT 'UNVALIDATED | VALID_READ_ONLY | INVALID_CREDENTIALS',
    created_ts_utc                DATETIME             NOT NULL,
    validated_ts_utc              DATETIME             NULL,
    rotated_ts_utc                DATETIME             NULL,
    revoked_ts_utc                DATETIME             NULL,

    PRIMARY KEY (trading_account_credential_id),

    -- Lookup index: active credential per account+venue
    KEY idx_tac_account_venue_status (trading_account_id, venue, credential_status),

    -- Deduplication lookup by fingerprint
    KEY idx_tac_fingerprint (credential_fingerprint),

    CONSTRAINT fk_tac_trading_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),

    CONSTRAINT chk_tac_status
        CHECK (credential_status IN ('ACTIVE', 'REVOKED', 'ROTATED', 'INVALID')),

    CONSTRAINT chk_tac_validation_state
        CHECK (validation_state IN ('UNVALIDATED', 'VALID_READ_ONLY', 'INVALID_CREDENTIALS'))

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Encrypted exchange API credentials. No plaintext credentials stored.';
