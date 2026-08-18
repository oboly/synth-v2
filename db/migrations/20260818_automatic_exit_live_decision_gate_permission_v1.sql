-- Issue #392 Phase 6 blocker B: decision-gate LIVE automatic-exit permission.
--
-- This grants decision-gate LIVE permission only -- it is NOT executor
-- operational LIVE authority, NOT a kill switch, NOT a credential, and NOT
-- broker/order authority of any kind. A decision_gate APPROVED LIVE result
-- under this table still requires the wholly separate executor-authority
-- gate (src/executor/execution_live_authority_v1.py) before any order may
-- ever be placed.
--
-- Lifecycle mirrors the corrected account_protection_policy_config_v1 model
-- (db/migrations/20260817_account_protection_policy_config_v1.sql): the
-- permission row is permanently immutable (UPDATE/DELETE always rejected,
-- including the "close the open window" transition), and superseding or
-- ending an open-ended (effective_until_ts_utc IS NULL) row is expressed
-- exclusively through an immutable, append-only revocation fact in the
-- companion automatic_exit_live_decision_gate_permission_revocation_v1
-- table, never by mutating the permission row itself. Migration artifact
-- only; not applied by this change.

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
    UNIQUE KEY uq_automatic_exit_live_permission_account_binding (
        automatic_exit_live_decision_gate_permission_id, trading_account_id
    ),
    KEY ix_automatic_exit_live_permission_lookup (trading_account_id, effective_from_ts_utc),
    CONSTRAINT fk_automatic_exit_live_permission_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT chk_automatic_exit_live_permission_flag CHECK (live_execution_permitted IN (0, 1)),
    CONSTRAINT chk_automatic_exit_live_permission_window CHECK (
        effective_until_ts_utc IS NULL OR effective_until_ts_utc > effective_from_ts_utc
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only, permanently immutable account-scoped decision-gate LIVE automatic-exit permission. Grants no executor, kill-switch, credential, or broker authority.';

-- Strictly append-only: no UPDATE, no DELETE, ever. A permission row's
-- window is fixed for its lifetime. Superseding or ending an open-ended row
-- is expressed exclusively through an immutable revocation fact below.
DELIMITER //
CREATE TRIGGER trg_automatic_exit_live_permission_v1_no_update
BEFORE UPDATE ON automatic_exit_live_decision_gate_permission_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic exit live decision-gate permission is immutable; append a revocation fact instead';
END//
CREATE TRIGGER trg_automatic_exit_live_permission_v1_no_delete
BEFORE DELETE ON automatic_exit_live_decision_gate_permission_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic exit live decision-gate permission is immutable; append a revocation fact instead';
END//
DELIMITER ;

-- Immutable, append-only revocation/supersession lifecycle facts for
-- automatic_exit_live_decision_gate_permission_v1. Multiple revocation facts
-- per permission row are permitted by design (e.g. an earlier scheduled
-- future revocation must never block a later immediate one from also being
-- recorded); the resolver treats a permission row as revoked at time T if
-- ANY of its revocation facts has effective_ts_utc <= T. trading_account_id
-- is denormalized from the referenced permission row, and the composite
-- foreign key below binds (automatic_exit_live_decision_gate_permission_id,
-- trading_account_id) together against the permission table's own matching
-- unique key -- MariaDB itself rejects a structurally corrupt row
-- referencing Account A's permission while claiming Account B's
-- trading_account_id, before it can ever reach the resolver's own
-- defense-in-depth mismatch check. A separate single-column FK straight to
-- trading_account is intentionally omitted: it would be redundant, since the
-- composite FK already transitively guarantees trading_account_id is a
-- valid account (via the permission row's own FK to trading_account)
-- without a second, independently-owned copy of that same invariant.
CREATE TABLE IF NOT EXISTS automatic_exit_live_decision_gate_permission_revocation_v1 (
    automatic_exit_live_decision_gate_permission_revocation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    automatic_exit_live_decision_gate_permission_id BIGINT UNSIGNED NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    revocation_version VARCHAR(16) NOT NULL,
    effective_ts_utc DATETIME(6) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    reason VARCHAR(512) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (automatic_exit_live_decision_gate_permission_revocation_id),
    KEY ix_automatic_exit_live_permission_revocation_binding (
        automatic_exit_live_decision_gate_permission_id, trading_account_id
    ),
    KEY ix_automatic_exit_live_permission_revocation_lookup (
        automatic_exit_live_decision_gate_permission_id, effective_ts_utc
    ),
    KEY ix_automatic_exit_live_permission_revocation_account (
        trading_account_id, effective_ts_utc
    ),
    CONSTRAINT fk_automatic_exit_live_permission_revocation_permission_account
        FOREIGN KEY (automatic_exit_live_decision_gate_permission_id, trading_account_id)
        REFERENCES automatic_exit_live_decision_gate_permission_v1 (
            automatic_exit_live_decision_gate_permission_id, trading_account_id
        ),
    CONSTRAINT chk_automatic_exit_live_permission_revocation_text CHECK (
        CHAR_LENGTH(TRIM(actor)) > 0 AND CHAR_LENGTH(TRIM(reason)) > 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Immutable, append-only revocation/supersession facts for automatic_exit_live_decision_gate_permission_v1. Never updated or deleted. Composite FK binds (permission_id, trading_account_id) to reject cross-account corruption at the DB boundary.';

DELIMITER //
CREATE TRIGGER trg_automatic_exit_live_permission_revocation_v1_no_update
BEFORE UPDATE ON automatic_exit_live_decision_gate_permission_revocation_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic exit live decision-gate permission revocation facts are append-only';
END//
CREATE TRIGGER trg_automatic_exit_live_permission_revocation_v1_no_delete
BEFORE DELETE ON automatic_exit_live_decision_gate_permission_revocation_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic exit live decision-gate permission revocation facts are append-only';
END//
DELIMITER ;
