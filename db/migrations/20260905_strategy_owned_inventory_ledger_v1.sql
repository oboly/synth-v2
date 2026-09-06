-- Issue #752: strategy-owned inventory ledger. decision_gate is the sole
-- owner. Migration artifact only; do not apply from this change.
--
-- No existing table owns this fact. account_position_snapshot (see
-- src/operations/run_broker_account_position_snapshot_writer_v1.py) is a
-- raw per-symbol broker-wallet snapshot -- reconciliation truth, unchanged
-- by this table. executor_execution_handoff/executor_execution_leg (see
-- 20260815_shared_executor_substrate_v1.sql) carry no strategy_bucket_id/
-- strategy_id/setup_id columns today. This table is therefore new
-- persistence for a fact reconciliation does not own, layered strictly on
-- top of (never replacing) reconciliation's broker-wallet balance truth:
--
--     broker wallet balance   = reconciliation fact (unchanged)
--     strategy-owned quantity = this table
--
-- Append-only, event-sourced: one immutable row per attributed BUY or SELL
-- fill event. Current owned quantity for a lineage is always the
-- deterministic sum over these rows
-- (src/decision_gate/strategy_owned_inventory_ledger_v1.py
-- compute_owned_quantity_v1), never a separately maintained mutable
-- counter, so ownership is always reconstructible from source fill
-- identity alone (restart-safe by construction).
--
-- Lineage identity -- the exact scope one strategy/trade may reduce:
--   (trading_account_id, venue, market, strategy_bucket_id, strategy_id,
--    strategy_version, setup_id)
-- Two lineages differing only in strategy/trade identity may both own
-- quantity in the identical (trading_account_id, venue, market) without
-- collision; each is summed independently.
--
-- order_identity is the canonical fill/order identity (e.g.
-- client_order_id, or client_order_id:leg_index for a multi-leg plan) used
-- for deterministic idempotent deduplication: the unique key below makes a
-- duplicate reconciliation event for the same order a no-op insert
-- conflict rather than a double-counted row.

CREATE TABLE IF NOT EXISTS strategy_owned_inventory_ledger_v1 (
    strategy_owned_inventory_ledger_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    market VARCHAR(32) NOT NULL,
    strategy_bucket_id VARCHAR(64) NOT NULL,
    strategy_id VARCHAR(64) NOT NULL,
    strategy_version VARCHAR(16) NOT NULL,
    setup_id VARCHAR(128) NOT NULL,
    execution_plan_reference_id VARCHAR(255) NOT NULL,
    order_identity VARCHAR(255) NOT NULL,
    side VARCHAR(4) NOT NULL,
    base_quantity DECIMAL(30,18) NOT NULL,
    quote_notional DECIMAL(30,18) NOT NULL,
    occurred_ts_utc DATETIME(6) NOT NULL,
    source_provenance VARCHAR(128) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (strategy_owned_inventory_ledger_id),
    UNIQUE KEY uq_strategy_owned_inventory_ledger_order_identity (
        trading_account_id, venue, market, order_identity
    ),
    KEY ix_strategy_owned_inventory_ledger_lineage (
        trading_account_id, venue, market, strategy_bucket_id, strategy_id,
        strategy_version, setup_id, occurred_ts_utc
    ),
    CONSTRAINT fk_strategy_owned_inventory_ledger_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT chk_strategy_owned_inventory_ledger_side CHECK (
        side IN ('BUY', 'SELL')
    ),
    CONSTRAINT chk_strategy_owned_inventory_ledger_base_quantity CHECK (
        base_quantity > 0
    ),
    CONSTRAINT chk_strategy_owned_inventory_ledger_quote_notional CHECK (
        quote_notional >= 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Issue #752: append-only, event-sourced strategy/trade-lineage fill attribution. Owned quantity is always SUM(BUY) - SUM(SELL) over these rows for one exact lineage; never a separately maintained counter. decision_gate-owned only.';

-- Strictly append-only: no UPDATE, no DELETE, ever. A correction is a new
-- row (e.g. a reversal event), never a mutation of an existing fact --
-- mirrors strategy_bucket_account_config_v1's and every other #279/#399
-- immutable-fact table's convention.
DELIMITER //
CREATE TRIGGER trg_strategy_owned_inventory_ledger_v1_no_update
BEFORE UPDATE ON strategy_owned_inventory_ledger_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'strategy owned inventory ledger is append-only; insert a new event instead';
END//
CREATE TRIGGER trg_strategy_owned_inventory_ledger_v1_no_delete
BEFORE DELETE ON strategy_owned_inventory_ledger_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'strategy owned inventory ledger is append-only; insert a new event instead';
END//
DELIMITER ;
