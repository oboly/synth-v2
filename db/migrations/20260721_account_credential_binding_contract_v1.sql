-- Migration: account_credential_binding_contract_v1
-- Idempotent: safe to re-run on MariaDB versions that support IF NOT EXISTS.
-- Purpose: additive non-secret credential identity and permission metadata for
--          deterministic account-to-credential binding.
--
-- Canonical binding:
--   trading_account_id + venue + permission_scope
--     -> exactly one ACTIVE trading_account_credential row.
--
-- No plaintext API keys or API secrets are added by this migration.

ALTER TABLE trading_account_credential
    ADD COLUMN IF NOT EXISTS credential_source VARCHAR(32) NOT NULL DEFAULT 'db_encrypted'
        COMMENT 'db_encrypted | legacy_profile_env_deprecated';

ALTER TABLE trading_account_credential
    ADD COLUMN IF NOT EXISTS permission_scope VARCHAR(32) NOT NULL DEFAULT 'READ_ONLY_PRIVATE'
        COMMENT 'READ_ONLY_PRIVATE | TRADE_EXECUTION';

ALTER TABLE trading_account_credential
    ADD COLUMN IF NOT EXISTS allowed_private_read TINYINT(1) NOT NULL DEFAULT 1
        COMMENT 'Credential metadata: private account reads are allowed.';

ALTER TABLE trading_account_credential
    ADD COLUMN IF NOT EXISTS allowed_order_write TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Credential metadata: broker order writes are allowed.';

ALTER TABLE trading_account_credential
    ADD COLUMN IF NOT EXISTS allowed_withdrawal TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Must remain 0. Synth never requires withdrawal-capable credentials.';

ALTER TABLE trading_account_credential
    ADD COLUMN IF NOT EXISTS last_validation_error_code VARCHAR(64) NULL
        COMMENT 'Safe non-secret credential validation error code.';

ALTER TABLE trading_account_credential
    ADD COLUMN IF NOT EXISTS active_permission_scope VARCHAR(32)
        GENERATED ALWAYS AS (
            CASE
                WHEN credential_status = 'ACTIVE' THEN permission_scope
                ELSE NULL
            END
        ) VIRTUAL
        COMMENT 'Generated column for one ACTIVE credential per account+venue+scope.';

ALTER TABLE trading_account_credential
    DROP CONSTRAINT IF EXISTS chk_tac_credential_source_v1;

ALTER TABLE trading_account_credential
    ADD CONSTRAINT chk_tac_credential_source_v1
        CHECK (credential_source IN ('db_encrypted', 'legacy_profile_env_deprecated'));

ALTER TABLE trading_account_credential
    DROP CONSTRAINT IF EXISTS chk_tac_permission_scope_v1;

ALTER TABLE trading_account_credential
    ADD CONSTRAINT chk_tac_permission_scope_v1
        CHECK (permission_scope IN ('READ_ONLY_PRIVATE', 'TRADE_EXECUTION'));

ALTER TABLE trading_account_credential
    DROP CONSTRAINT IF EXISTS chk_tac_capability_flags_v1;

ALTER TABLE trading_account_credential
    ADD CONSTRAINT chk_tac_capability_flags_v1
        CHECK (
            allowed_private_read IN (0, 1)
            AND allowed_order_write IN (0, 1)
            AND allowed_withdrawal = 0
            AND NOT (
                permission_scope = 'READ_ONLY_PRIVATE'
                AND allowed_order_write <> 0
            )
        );

CREATE UNIQUE INDEX IF NOT EXISTS uq_tac_active_account_venue_scope_v1
    ON trading_account_credential (
        trading_account_id,
        venue,
        active_permission_scope
    );
