-- Migration: manual_execution_submission_leg_v1
-- Status: CREATED BUT NOT APPLIED to production as of 2026-08-13 (Issue #369).
-- Boundary: schema only. No broker calls, no order submission, no live
--           enablement. Live trading permission remains NOT_GRANTED.
--
-- Purpose:
--   One canonical row per (manual_execution_plan_snapshot_id, leg_index),
--   the single per-leg broker submission identity and state machine for the
--   crash-safe manual SELL ladder submission orchestrator (Issue #369). No
--   secret credential material and no arbitrary raw broker payload is
--   stored here; only normalized non-secret evidence.
--
-- Concurrency/idempotency authority:
--   Per-leg row creation is a plain INSERT (never upsert): the UNIQUE KEY
--   uq_mesl_plan_leg is the single authority that guarantees at most one
--   process ever "owns" origination of a given leg row. The
--   PREPARED -> SUBMISSION_UNCERTAIN pre-broker-call transition is a single
--   conditional UPDATE guarded by WHERE submission_state = 'PREPARED'; only
--   the transaction whose UPDATE matches (cursor.rowcount == 1) may call the
--   broker. This is the same authority pattern already used by
--   manual_execution_executor_handoff._resolve_claim (Issue #206) — process
--   memory is never the authority. This additive per-leg authority is
--   sufficient to guarantee two executor processes can never both submit
--   the same leg (and therefore never both submit the same handoff, since
--   leg_index=1 must be won before any later leg is attempted); no
--   additional claim_state is added to manual_execution_executor_handoff by
--   this migration.
--
-- Prerequisites:
--   20260812_manual_execution_executor_handoff_v1.sql
--
-- Rollback limitations: MariaDB DDL implicitly commits. Drop the trigger
-- before dropping the table, and only before any leg row has left PREPARED.

CREATE TABLE manual_execution_submission_leg (
    submission_leg_id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    manual_execution_executor_handoff_id BIGINT UNSIGNED NOT NULL,
    manual_execution_plan_snapshot_id    BIGINT UNSIGNED NOT NULL,
    leg_index                            INT UNSIGNED NOT NULL,
    trading_account_id                   BIGINT UNSIGNED NOT NULL,
    venue                                VARCHAR(32) NOT NULL,
    market                                VARCHAR(64) NOT NULL,
    side                                  VARCHAR(8) NOT NULL,

    client_order_id                      CHAR(36) NOT NULL
        COMMENT 'Deterministic UUIDv5 derived from plan_snapshot_id+leg_index+trading_account_id+venue+market. Never random.',
    operator_id                          BIGINT UNSIGNED NOT NULL
        COMMENT 'Explicit canonical Bitvavo operatorId for the Synth executor/bot. Never inferred from display name.',

    immutable_price                      DECIMAL(20,10) NOT NULL
        COMMENT 'Exact persisted execution_planner leg price. Executor never recomputes this.',
    immutable_quantity                   DECIMAL(20,10) NOT NULL
        COMMENT 'Exact persisted execution_planner leg quantity. Executor never recomputes this.',

    submission_state                     VARCHAR(24) NOT NULL DEFAULT 'PREPARED'
        COMMENT 'PREPARED | SUBMISSION_UNCERTAIN | SUBMITTED | OPEN | PARTIALLY_FILLED | FILLED | CANCELLED | REJECTED | FAILED',
    broker_order_id                      VARCHAR(128) NULL,
    broker_status                        VARCHAR(32) NULL,
    attempt_started_ts_utc               DATETIME(6) NULL,
    broker_ack_ts_utc                    DATETIME(6) NULL,
    last_reconciled_ts_utc               DATETIME(6) NULL,
    safe_error_code                      VARCHAR(64) NULL
        COMMENT 'Normalized non-secret error classification only. Never raw broker response text.',
    created_ts_utc                       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (submission_leg_id),
    UNIQUE KEY uq_mesl_plan_leg (manual_execution_plan_snapshot_id, leg_index),
    UNIQUE KEY uq_mesl_client_order_id (client_order_id),
    KEY idx_mesl_handoff (manual_execution_executor_handoff_id),
    KEY idx_mesl_account_venue (trading_account_id, venue),

    CONSTRAINT fk_mesl_handoff
        FOREIGN KEY (manual_execution_executor_handoff_id)
        REFERENCES manual_execution_executor_handoff (manual_execution_executor_handoff_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_mesl_plan_snapshot
        FOREIGN KEY (manual_execution_plan_snapshot_id)
        REFERENCES manual_execution_plan_snapshot (manual_execution_plan_snapshot_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_mesl_trading_account
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,

    CONSTRAINT chk_mesl_side CHECK (side = 'SELL'),
    CONSTRAINT chk_mesl_submission_state CHECK (submission_state IN (
        'PREPARED', 'SUBMISSION_UNCERTAIN', 'SUBMITTED', 'OPEN',
        'PARTIALLY_FILLED', 'FILLED', 'CANCELLED', 'REJECTED', 'FAILED'
    )),
    CONSTRAINT chk_mesl_price_positive CHECK (immutable_price > 0),
    CONSTRAINT chk_mesl_quantity_positive CHECK (immutable_quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='One row per (plan_snapshot_id, leg_index). Per-leg crash-safe broker submission identity and state machine (Issue #369). No secret material stored.';

DELIMITER $$

CREATE TRIGGER trg_mesl_identity_immutable
BEFORE UPDATE ON manual_execution_submission_leg
FOR EACH ROW
BEGIN
    IF NOT (
        OLD.manual_execution_executor_handoff_id <=> NEW.manual_execution_executor_handoff_id
        AND OLD.manual_execution_plan_snapshot_id <=> NEW.manual_execution_plan_snapshot_id
        AND OLD.leg_index <=> NEW.leg_index
        AND OLD.trading_account_id <=> NEW.trading_account_id
        AND OLD.venue <=> NEW.venue
        AND OLD.market <=> NEW.market
        AND OLD.side <=> NEW.side
        AND OLD.client_order_id <=> NEW.client_order_id
        AND OLD.operator_id <=> NEW.operator_id
        AND OLD.immutable_price <=> NEW.immutable_price
        AND OLD.immutable_quantity <=> NEW.immutable_quantity
        AND OLD.created_ts_utc <=> NEW.created_ts_utc
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MANUAL_EXECUTION_SUBMISSION_LEG_IDENTITY_IS_IMMUTABLE';
    END IF;
    IF OLD.submission_state IN ('FILLED', 'CANCELLED', 'REJECTED', 'FAILED')
       AND NEW.submission_state <> OLD.submission_state THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MANUAL_EXECUTION_SUBMISSION_LEG_ALREADY_TERMINAL';
    END IF;
END$$

CREATE TRIGGER trg_mesl_no_delete
BEFORE DELETE ON manual_execution_submission_leg
FOR EACH ROW SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'MANUAL_EXECUTION_SUBMISSION_LEG_IS_IMMUTABLE'$$

DELIMITER ;

-- Deterministic down contract (manual, only before rows are created):
-- DROP TRIGGER trg_mesl_no_delete;
-- DROP TRIGGER trg_mesl_identity_immutable;
-- DROP TABLE manual_execution_submission_leg;
