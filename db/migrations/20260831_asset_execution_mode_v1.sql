-- Issue #638: separate canonical instrument identity from automated execution capability.
-- Existing assets default to AUTOMATED to preserve current behavior.
-- Manual/RFQ/NONE assets remain analyzable but must not reach automated order submission.

ALTER TABLE asset
    ADD COLUMN execution_mode VARCHAR(32) NOT NULL DEFAULT 'AUTOMATED' AFTER is_tradeable;

ALTER TABLE asset
    ADD CONSTRAINT chk_asset_execution_mode_v1
    CHECK (execution_mode IN ('AUTOMATED', 'MANUAL_RFQ', 'MANUAL', 'NONE'));
