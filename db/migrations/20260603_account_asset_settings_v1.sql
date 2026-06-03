-- Migration: account_asset_settings_v1
-- Boundary: account-scoped settings only · no broker writes · no order submission
-- Purpose: extend account_asset with missing settings-management fields while reusing
-- existing created_ts / updated_ts columns from the multi-account asset foundation.

ALTER TABLE account_asset
    ADD COLUMN IF NOT EXISTS disabled_reason VARCHAR(64) DEFAULT NULL
        COMMENT 'MANUAL_DISABLE | PAUSE_24H | NULL for enabled rows'
        AFTER disabled_until_utc;

ALTER TABLE account_asset
    ADD COLUMN IF NOT EXISTS first_seen_at_utc DATETIME DEFAULT NULL
        COMMENT 'First time account_asset row was discovered or manually added'
        AFTER source;

ALTER TABLE account_asset
    ADD COLUMN IF NOT EXISTS last_seen_at_utc DATETIME DEFAULT NULL
        COMMENT 'Most recent discovery/add visibility timestamp'
        AFTER first_seen_at_utc;

UPDATE account_asset
SET
    first_seen_at_utc = COALESCE(first_seen_at_utc, created_ts),
    last_seen_at_utc = COALESCE(last_seen_at_utc, updated_ts)
WHERE first_seen_at_utc IS NULL
   OR last_seen_at_utc IS NULL;
