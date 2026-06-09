-- Migration: trading_account_credential_add_valid_private_read
-- Idempotent: safe to re-run on MariaDB 10.2.1+.
-- Purpose: extend validation_state CHECK constraint to include VALID_PRIVATE_READ.
--          Bitvavo does not expose reliable read-only capability metadata,
--          so provisioning maps successful validation to VALID_PRIVATE_READ
--          rather than VALID_READ_ONLY.

ALTER TABLE trading_account_credential
    DROP CONSTRAINT IF EXISTS chk_tac_validation_state;

ALTER TABLE trading_account_credential
    ADD CONSTRAINT chk_tac_validation_state
        CHECK (validation_state IN ('UNVALIDATED', 'VALID_READ_ONLY', 'VALID_PRIVATE_READ', 'INVALID_CREDENTIALS'));
