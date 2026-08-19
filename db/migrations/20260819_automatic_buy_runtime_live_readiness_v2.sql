-- Issue #399 Phase 7B: add immutable LIVE-capable account evidence to the
-- automatic BUY runtime input snapshot. Artifact only; not applied here.
--
-- This column records snapshot evidence. It does NOT mutate
-- trading_account.live_trading_enabled and does not activate LIVE trading.

ALTER TABLE automatic_buy_runtime_input_v1
    ADD COLUMN IF NOT EXISTS live_trading_enabled TINYINT(1) NOT NULL DEFAULT 0
    AFTER automatic_buy_execution_enabled;

ALTER TABLE automatic_buy_runtime_input_v1
    ADD CONSTRAINT chk_automatic_buy_runtime_live_trading_enabled
        CHECK (live_trading_enabled IN (0, 1));
