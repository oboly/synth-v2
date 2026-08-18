-- Issue #392 Phase 6 blocker B: decision-gate LIVE automatic-exit permission.
--
-- This grants decision-gate LIVE permission only -- it is NOT executor
-- operational LIVE authority, NOT a kill switch, NOT a credential, and NOT
-- broker/order authority of any kind. A decision_gate APPROVED LIVE result
-- under this table still requires the wholly separate executor-authority
-- gate (src/executor/execution_live_authority_v1.py) before any order may
-- ever be placed.
--
-- Mirrors automatic_exit_account_permission_v1's append-only, account-scoped,
-- effective-window shape exactly (see 20260814_automatic_exit_runtime_contract_v1.sql).
-- Migration artifact only; not applied by this change.

CREATE TABLE IF NOT EXISTS automatic_exit_live_decision_gate_permission_v1 (
    automatic_exit_live_decision_gate_permission_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    live_execution_permitted TINYINT(1) NOT NULL DEFAULT 0,
    effective_from_ts_utc DATETIME(6) NOT NULL,
    effective_until_ts_utc DATETIME(6) NULL,
    permission_version VARCHAR(32) NOT NULL DEFAULT '1',
    source_provenance VARCHAR(128) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (automatic_exit_live_decision_gate_permission_id),
    KEY ix_automatic_exit_live_permission_lookup (trading_account_id, effective_from_ts_utc),
    CONSTRAINT fk_automatic_exit_live_permission_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT chk_automatic_exit_live_permission_flag CHECK (live_execution_permitted IN (0, 1)),
    CONSTRAINT chk_automatic_exit_live_permission_window CHECK (
        effective_until_ts_utc IS NULL OR effective_until_ts_utc > effective_from_ts_utc
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only account-scoped decision-gate LIVE automatic-exit permission. Grants no executor, kill-switch, credential, or broker authority.';
