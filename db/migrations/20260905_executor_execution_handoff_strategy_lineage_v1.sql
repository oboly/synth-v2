-- Issue #756 Codex block: propagate the minimum immutable strategy-ownership
-- lineage identity through the existing shared #206 executor handoff
-- contract (executor_execution_handoff), so a real fill confirmation can
-- attribute a strategy-owned inventory ledger event without inventing a
-- second reconciliation truth or duplicating executor architecture.
--
-- NULL for every non-automatic-buy handoff (manual execution untouched and
-- unaffected). All four fields are set together (only by the automatic-buy
-- execution handoff adapter) or not at all -- never partially populated.
--
-- Migration artifact only; do not apply from this change.

ALTER TABLE executor_execution_handoff
  ADD COLUMN strategy_bucket_id VARCHAR(64) NULL AFTER side,
  ADD COLUMN strategy_id VARCHAR(64) NULL AFTER strategy_bucket_id,
  ADD COLUMN strategy_version VARCHAR(32) NULL AFTER strategy_id,
  ADD COLUMN setup_id VARCHAR(64) NULL AFTER strategy_version,
  ADD CONSTRAINT chk_eeh_strategy_lineage_all_or_none CHECK (
    (strategy_bucket_id IS NULL AND strategy_id IS NULL AND strategy_version IS NULL AND setup_id IS NULL)
    OR (strategy_bucket_id IS NOT NULL AND strategy_id IS NOT NULL AND strategy_version IS NOT NULL AND setup_id IS NOT NULL)
  );

DROP TRIGGER IF EXISTS trg_eeh_immutable;
DELIMITER //
CREATE TRIGGER trg_eeh_immutable BEFORE UPDATE ON executor_execution_handoff FOR EACH ROW BEGIN
 IF NOT (
   OLD.plan_source <=> NEW.plan_source AND OLD.plan_reference_id <=> NEW.plan_reference_id
   AND OLD.plan_content_hash <=> NEW.plan_content_hash AND OLD.trading_account_id <=> NEW.trading_account_id
   AND OLD.venue <=> NEW.venue AND OLD.market <=> NEW.market AND OLD.side <=> NEW.side
   AND OLD.strategy_bucket_id <=> NEW.strategy_bucket_id AND OLD.strategy_id <=> NEW.strategy_id
   AND OLD.strategy_version <=> NEW.strategy_version AND OLD.setup_id <=> NEW.setup_id
   AND OLD.executor_mode <=> NEW.executor_mode AND OLD.executor_identity <=> NEW.executor_identity
   AND OLD.runtime_owner <=> NEW.runtime_owner AND OLD.executor_credential_binding_id <=> NEW.executor_credential_binding_id
 ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='executor handoff identity immutable'; END IF;
END//
DELIMITER ;

-- Bucket-scoped BUY reservation read model index: BLOCKER 1's bucket-scoped
-- pending-BUY-exposure read model (src/decision_gate/strategy_bucket_buy_reservation_v1.py)
-- filters executor_execution_leg by (trading_account_id, side, state) joined
-- to executor_execution_handoff by strategy_bucket_id across every market in
-- the bucket -- this index supports that join/filter path.
CREATE INDEX idx_eeh_account_bucket ON executor_execution_handoff (trading_account_id, strategy_bucket_id);
