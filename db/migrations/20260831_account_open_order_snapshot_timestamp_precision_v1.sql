-- Issue #644: account_open_order_snapshot.snapshot_ts_utc was DATETIME(0)
-- while every other aligned account-state component (balance snapshot,
-- position snapshot, open-order run header, account-state run header) is
-- DATETIME(6). The exact-account runner writes one Python microsecond
-- datetime for all components and then re-queries the open-order rows with
-- that same microsecond value, so the truncated column caused a spurious
-- OPEN_ORDER_SNAPSHOT_COUNT_MISMATCH even though the rows were written.
--
-- This migration only widens the column precision. It preserves NOT NULL
-- and the existing (trading_account_id, snapshot_ts_utc, broker_order_id)
-- unique key and the market index. No data is rounded or truncated by this
-- change -- existing DATETIME(0) values remain exact, just represented with
-- a zero microsecond component in DATETIME(6).
--
-- Boundary: schema-only · no broker writes · no order submission ·
-- no decision_gate/execution_planner/executor changes.

ALTER TABLE account_open_order_snapshot
    MODIFY COLUMN snapshot_ts_utc DATETIME(6) NOT NULL;
