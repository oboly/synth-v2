-- Migration: manual_execution_executor_handoff_v1
-- Status: CREATED BUT NOT APPLIED to production as of 2026-08-12 (Issue #206).
-- Boundary: schema only. No broker calls, no order submission, no live
--           enablement. Live trading permission remains NOT_GRANTED.
--
-- Purpose:
--   1. executor_credential_binding — deny-by-default binding of exactly one
--      TRADE_EXECUTION credential scope to one explicit
--      (trading_account_id, venue, executor_identity, runtime_owner). No
--      plaintext credential material is added here; this table only points
--      at an existing trading_account_credential row, and a composite
--      foreign key ties the binding's own trading_account_id/venue/
--      permission_scope to that referenced credential's identity, so a
--      binding can never silently point at a credential for a different
--      account, venue, or scope.
--   2. manual_execution_executor_handoff — the single immutable identity
--      that authorizes handing one decision_gate-approved, execution_planner
--      -snapshotted manual execution plan to exactly one executor
--      intake/claim/consume lifecycle. One row per
--      manual_execution_plan_snapshot (UNIQUE), so a duplicate intake
--      attempt for the same snapshot can never create a second handoff.
--
-- Prerequisites:
--   20260609_trading_account_credential_v1.sql
--   20260721_account_credential_binding_contract_v1.sql
--   20260811_manual_execution_plan_snapshot_idempotency_v1.sql
--
-- Rollback limitations: MariaDB DDL implicitly commits. Drop triggers before
-- dropping tables, and only before any handoff row has been claimed/consumed.
--
-- Credential identity match: trading_account_credential_id alone is not
-- sufficient to trust a binding's trading_account_id/venue/permission_scope
-- — those are enforced to agree with the referenced credential row itself
-- via the composite foreign key fk_ecb_credential_identity below, backed by
-- this trivially-satisfiable additive unique key (trading_account_credential_id
-- is already the table's primary key, so no existing row can violate it).

ALTER TABLE trading_account_credential
    ADD UNIQUE KEY uq_tac_credential_identity_v1 (
        trading_account_credential_id, trading_account_id, venue, permission_scope
    );

CREATE TABLE executor_credential_binding (
    executor_credential_binding_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trading_account_credential_id  BIGINT UNSIGNED NOT NULL,
    trading_account_id             BIGINT UNSIGNED NOT NULL,
    venue                          VARCHAR(32) NOT NULL,
    permission_scope               VARCHAR(32) NOT NULL DEFAULT 'TRADE_EXECUTION',
    executor_identity              VARCHAR(128) NOT NULL
        COMMENT 'Explicit executor/agent identity permitted to use this credential scope.',
    runtime_owner                  VARCHAR(64) NOT NULL
        COMMENT 'Explicit host/service owner, e.g. devlap, odroid, db_host.',
    binding_status                 VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'
        COMMENT 'ACTIVE | REVOKED',
    created_ts_utc                 DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    revoked_ts_utc                 DATETIME(6) NULL,

    active_binding_scope VARCHAR(32)
        GENERATED ALWAYS AS (
            CASE WHEN binding_status = 'ACTIVE' THEN permission_scope ELSE NULL END
        ) VIRTUAL
        COMMENT 'Generated column backing one ACTIVE binding per identity tuple.',

    PRIMARY KEY (executor_credential_binding_id),
    UNIQUE KEY uq_ecb_credential_identity (
        trading_account_credential_id, executor_identity, runtime_owner
    ),
    UNIQUE KEY uq_ecb_active_identity_scope (
        trading_account_id, venue, executor_identity, runtime_owner, active_binding_scope
    ),
    KEY idx_ecb_account_venue (trading_account_id, venue),

    CONSTRAINT fk_ecb_credential_identity
        FOREIGN KEY (trading_account_credential_id, trading_account_id, venue, permission_scope)
        REFERENCES trading_account_credential (
            trading_account_credential_id, trading_account_id, venue, permission_scope
        )
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_ecb_trading_account
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,

    CONSTRAINT chk_ecb_permission_scope
        CHECK (permission_scope = 'TRADE_EXECUTION'),
    CONSTRAINT chk_ecb_binding_status
        CHECK (binding_status IN ('ACTIVE', 'REVOKED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Deny-by-default credential-scope binding: one TRADE_EXECUTION credential per explicit executor identity + runtime owner. No secret material stored.';

CREATE TABLE manual_execution_executor_handoff (
    manual_execution_executor_handoff_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    manual_execution_request_id          BIGINT UNSIGNED NOT NULL,
    manual_execution_approval_id         BIGINT UNSIGNED NOT NULL,
    manual_execution_plan_snapshot_id    BIGINT UNSIGNED NOT NULL,
    trading_account_id                   BIGINT UNSIGNED NOT NULL,
    venue                                VARCHAR(32) NOT NULL,
    market                               VARCHAR(64) NOT NULL,
    side                                 VARCHAR(8) NOT NULL,
    executor_mode                        VARCHAR(16) NOT NULL
        COMMENT 'DRY_RUN | PAPER | LIVE_DISABLED. LIVE_DISABLED is never claimable.',
    executor_identity                    VARCHAR(128) NOT NULL,
    runtime_owner                        VARCHAR(64) NOT NULL,
    executor_credential_binding_id       BIGINT UNSIGNED NOT NULL,

    claim_state                          VARCHAR(16) NOT NULL DEFAULT 'CLAIMED'
        COMMENT 'CLAIMED | CONSUMED | FAILED. CONSUMED/FAILED are terminal.',
    claimed_ts_utc                       DATETIME(6) NOT NULL,
    consumed_ts_utc                      DATETIME(6) NULL,
    outcome_code                         VARCHAR(64) NULL,
    outcome_detail                       VARCHAR(255) NULL,
    created_ts_utc                       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (manual_execution_executor_handoff_id),
    UNIQUE KEY uq_meeh_plan_snapshot (manual_execution_plan_snapshot_id),
    KEY idx_meeh_account_venue (trading_account_id, venue),

    CONSTRAINT fk_meeh_request
        FOREIGN KEY (manual_execution_request_id)
        REFERENCES manual_execution_request (manual_execution_request_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_meeh_approval
        FOREIGN KEY (manual_execution_approval_id)
        REFERENCES manual_execution_approval (manual_execution_approval_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_meeh_plan_snapshot
        FOREIGN KEY (manual_execution_plan_snapshot_id)
        REFERENCES manual_execution_plan_snapshot (manual_execution_plan_snapshot_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_meeh_trading_account
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_meeh_credential_binding
        FOREIGN KEY (executor_credential_binding_id)
        REFERENCES executor_credential_binding (executor_credential_binding_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,

    CONSTRAINT chk_meeh_side CHECK (side = 'SELL'),
    CONSTRAINT chk_meeh_executor_mode
        CHECK (executor_mode IN ('DRY_RUN', 'PAPER', 'LIVE_DISABLED')),
    CONSTRAINT chk_meeh_claim_state
        CHECK (claim_state IN ('CLAIMED', 'CONSUMED', 'FAILED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Immutable executor handoff identity. One row per plan snapshot. No broker order/fill/cancel state is stored here.';

DELIMITER $$

CREATE TRIGGER trg_meeh_no_identity_mutation
BEFORE UPDATE ON manual_execution_executor_handoff
FOR EACH ROW
BEGIN
    IF OLD.claim_state IN ('CONSUMED', 'FAILED') THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MANUAL_EXECUTION_EXECUTOR_HANDOFF_ALREADY_TERMINAL';
    END IF;
    IF NOT (
        OLD.manual_execution_request_id <=> NEW.manual_execution_request_id
        AND OLD.manual_execution_approval_id <=> NEW.manual_execution_approval_id
        AND OLD.manual_execution_plan_snapshot_id <=> NEW.manual_execution_plan_snapshot_id
        AND OLD.trading_account_id <=> NEW.trading_account_id
        AND OLD.venue <=> NEW.venue
        AND OLD.market <=> NEW.market
        AND OLD.side <=> NEW.side
        AND OLD.executor_mode <=> NEW.executor_mode
        AND OLD.executor_identity <=> NEW.executor_identity
        AND OLD.runtime_owner <=> NEW.runtime_owner
        AND OLD.executor_credential_binding_id <=> NEW.executor_credential_binding_id
        AND OLD.claimed_ts_utc <=> NEW.claimed_ts_utc
        AND OLD.created_ts_utc <=> NEW.created_ts_utc
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MANUAL_EXECUTION_EXECUTOR_HANDOFF_IDENTITY_IS_IMMUTABLE';
    END IF;
    IF NOT (OLD.claim_state = 'CLAIMED' AND NEW.claim_state IN ('CONSUMED', 'FAILED')) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MANUAL_EXECUTION_EXECUTOR_HANDOFF_INVALID_CLAIM_TRANSITION';
    END IF;
END$$

CREATE TRIGGER trg_meeh_no_delete
BEFORE DELETE ON manual_execution_executor_handoff
FOR EACH ROW SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'MANUAL_EXECUTION_EXECUTOR_HANDOFF_IS_IMMUTABLE'$$

DELIMITER ;

-- Deterministic down contract (manual, only before rows are created):
-- DROP TRIGGER trg_meeh_no_delete;
-- DROP TRIGGER trg_meeh_no_identity_mutation;
-- DROP TABLE manual_execution_executor_handoff;
-- DROP TABLE executor_credential_binding;
-- ALTER TABLE trading_account_credential DROP INDEX uq_tac_credential_identity_v1;
