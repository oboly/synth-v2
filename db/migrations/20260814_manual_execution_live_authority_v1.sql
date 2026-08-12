-- Migration: manual_execution_live_authority_v1
-- Status: CREATED BUT NOT APPLIED to production as of 2026-08-14 (Issue #369
-- review follow-up). Boundary: schema only. No broker calls, no order
-- submission, no live enablement. Live trading permission remains
-- NOT_GRANTED.
--
-- Purpose:
--   The single canonical PERSISTED LIVE permission record for one explicit
--   manual_execution_executor_handoff (Issue #206). Its absence is the
--   default and is what keeps a DRY_RUN/PAPER handoff from being usable for
--   a real broker write, independent of any environment variable an
--   operator may set — see
--   src.executor.manual_execution_live_authority_v1 and
--   src.executor.manual_execution_live_submission_v1 for the two-layer
--   contract this table backs:
--     1. this table            = the canonical persisted permission
--                                 (WHO/WHAT is allowed), bound to one exact
--                                 handoff identity, created only by an
--                                 explicit separate operator grant action;
--     2. SYNTH_MANUAL_LIVE_EXECUTION_AUTHORIZATION_HANDOFF_ID (env, see
--        src.executor.manual_live_authorization_v1) = a same-process
--                                 runtime activation gate (freshness/
--                                 intent-at-this-moment), never a substitute
--                                 for #1.
--   A LIVE submission requires BOTH; neither alone is sufficient.
--
-- Additive only: does not modify manual_execution_executor_handoff
-- (20260812_manual_execution_executor_handoff_v1.sql) or its CHECK/trigger
-- contract. #206's executor_mode remains DRY_RUN/PAPER-only at intake, by
-- design — this table is a separate, later, explicit permission layered on
-- top of an already-claimed handoff, never an upgrade of executor_mode.
--
-- Prerequisites:
--   20260812_manual_execution_executor_handoff_v1.sql
--
-- Rollback limitations: MariaDB DDL implicitly commits. Drop triggers
-- before dropping the table, and only before any authority row exists.

CREATE TABLE manual_execution_live_authority (
    manual_execution_live_authority_id   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    manual_execution_executor_handoff_id BIGINT UNSIGNED NOT NULL,
    manual_execution_request_id          BIGINT UNSIGNED NOT NULL,
    manual_execution_approval_id         BIGINT UNSIGNED NOT NULL,
    manual_execution_plan_snapshot_id    BIGINT UNSIGNED NOT NULL,
    trading_account_id                   BIGINT UNSIGNED NOT NULL,
    venue                                VARCHAR(32) NOT NULL,
    executor_identity                    VARCHAR(128) NOT NULL,
    runtime_owner                        VARCHAR(64) NOT NULL,
    executor_credential_binding_id       BIGINT UNSIGNED NOT NULL,

    authorized_by                        VARCHAR(128) NOT NULL
        COMMENT 'Explicit operator identity granting LIVE authority for this exact handoff. Never inferred.',
    authorized_ts_utc                    DATETIME(6) NOT NULL,
    created_ts_utc                       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (manual_execution_live_authority_id),
    UNIQUE KEY uq_mela_handoff (manual_execution_executor_handoff_id),

    CONSTRAINT fk_mela_handoff
        FOREIGN KEY (manual_execution_executor_handoff_id)
        REFERENCES manual_execution_executor_handoff (manual_execution_executor_handoff_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_mela_request
        FOREIGN KEY (manual_execution_request_id)
        REFERENCES manual_execution_request (manual_execution_request_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_mela_approval
        FOREIGN KEY (manual_execution_approval_id)
        REFERENCES manual_execution_approval (manual_execution_approval_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_mela_plan_snapshot
        FOREIGN KEY (manual_execution_plan_snapshot_id)
        REFERENCES manual_execution_plan_snapshot (manual_execution_plan_snapshot_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_mela_trading_account
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_mela_credential_binding
        FOREIGN KEY (executor_credential_binding_id)
        REFERENCES executor_credential_binding (executor_credential_binding_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Persisted LIVE permission for exactly one manual_execution_executor_handoff. Absence = LIVE denied. Never auto-created.';

DELIMITER $$

CREATE TRIGGER trg_mela_immutable
BEFORE UPDATE ON manual_execution_live_authority
FOR EACH ROW SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'MANUAL_EXECUTION_LIVE_AUTHORITY_IS_IMMUTABLE'$$

CREATE TRIGGER trg_mela_no_delete
BEFORE DELETE ON manual_execution_live_authority
FOR EACH ROW SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'MANUAL_EXECUTION_LIVE_AUTHORITY_IS_IMMUTABLE'$$

DELIMITER ;

-- Deterministic down contract (manual, only before rows are created):
-- DROP TRIGGER trg_mela_no_delete;
-- DROP TRIGGER trg_mela_immutable;
-- DROP TABLE manual_execution_live_authority;
