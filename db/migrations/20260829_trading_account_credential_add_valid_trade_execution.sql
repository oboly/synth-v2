-- Issue #584: add explicit validated TRADE_EXECUTION credential state.
-- Additive schema evolution only. Historical migrations remain immutable.
--
-- Safety:
--   broker_private_calls=0
--   broker_writes=0
--   order_submission=0
--   live_orders=0

ALTER TABLE trading_account_credential
  DROP CONSTRAINT chk_tac_validation_state,
  ADD CONSTRAINT chk_tac_validation_state CHECK (
    validation_state IN (
      'UNVALIDATED',
      'VALID_READ_ONLY',
      'VALID_PRIVATE_READ',
      'VALID_TRADE_EXECUTION',
      'INVALID_CREDENTIALS'
    )
  );
