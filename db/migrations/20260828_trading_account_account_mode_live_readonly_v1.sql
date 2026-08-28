-- Migration: trading_account_account_mode_live_readonly
-- Idempotent: safe to re-run on MariaDB 10.2.1+ (this environment: 11.8.6-MariaDB).
-- Purpose: extend account_mode CHECK constraint to include 'live_readonly',
--          the canonical third account_mode value introduced by the
--          account_mode contract (PR #570, src/account/account_mode_contract_v1.py).
--          Schema only: no row is inserted, updated, or deleted by this
--          migration, and live_trading_enabled is not touched.
--
-- MIGRATION_STATE=CREATED_NOT_APPLIED
--
-- Preserves chk_trading_account_live_requires_enabled untouched.

ALTER TABLE trading_account
    DROP CONSTRAINT IF EXISTS chk_trading_account_mode;

ALTER TABLE trading_account
    ADD CONSTRAINT chk_trading_account_mode
        CHECK (account_mode IN ('paper', 'live_readonly', 'live'));
