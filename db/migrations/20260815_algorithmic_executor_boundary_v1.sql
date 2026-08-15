-- Migration: algorithmic_executor_boundary_v1
-- Status: CREATED BUT NOT APPLIED to production as of 2026-08-15 (Issue #206).
-- Boundary: schema only. No broker calls, no order submission, no live
--           enablement. Live trading permission remains NOT_GRANTED.
--
-- Purpose:
--   Side-neutral executor boundary shared by algorithm-driven SELL (#392)
--   and algorithm-driven BUY (#399). Generalizes the manual_execution_*
--   executor tables (20260812/20260813/20260814) without modifying or
--   dropping them -- the manual lane keeps its own tables unchanged.
--
--   1. executor_execution_handoff -- the single immutable identity that
--      authorizes handing one already-approved, already-immutable execution
--      plan (produced by whichever upstream lane -- manual, automatic exit,
--      future automatic entry -- owns plan construction) to exactly one
--      executor intake/claim/consume lifecycle. Unlike
--      manual_execution_executor_handoff, this table does NOT foreign-key
--      into a specific upstream plan table: #392/#399 plan persistence is
--      owned by those issues, not this one. Instead the exact approved plan
--      is bound by (plan_source, plan_reference_id) identity plus a
--      plan_content_hash (sha256 of the canonical immutable plan payload),
--      so a duplicate/retried intake for the same plan can never silently
--      diverge, and a caller can never claim a handoff whose reference
--      identity was already used for a different plan content.
--   2. executor_execution_leg -- side-neutral generalization of
--      manual_execution_submission_leg. Same crash-safe claim/attempt/
--      resolve concurrency authority (insert-wins origination, conditional
--      UPDATE ... WHERE submission_state = 'PREPARED' attempt-claim). Adds
--      RECONCILIATION_REQUIRED: reached only when a broker lookup
--      definitively confirms no such order exists after SUBMISSION_UNCERTAIN
--      -- V1 orchestration code must never automatically leave this state
--      (no automatic second POST); only an explicit, separately-audited
--      reconciliation action may re-arm it back to PREPARED.
--   3. executor_live_authority -- P0-D bounded, revocable, auditable LIVE
--      permission scoped to (trading_account_id, venue, side[, market]).
--      Deliberately NOT bound to a specific handoff/plan (unlike
--      manual_execution_live_authority): #392/#399 must be able to check
--      "is LIVE authorized for this account+venue+side right now" before a
--      specific plan exists. Absence is the default (deny-by-default).
--      effective_until_ts_utc is mandatory (NOT NULL) so every grant is
--      bounded; revoked_ts_utc provides independent early revocation.
--   4. executor_kill_switch -- P0-D global emergency override. Append-only;
--      the most recent row is authoritative. No row = not engaged (the
--      default-deny posture already comes from the absence of
--      executor_live_authority rows -- the kill switch's only job is the
--      emergency override that can force-deny regardless of any granted
--      per-account authority).
--
-- Prerequisites:
--   20260721_account_credential_binding_contract_v1.sql (trading_account_credential)
--   20260812_manual_execution_executor_handoff_v1.sql (executor_credential_binding -- reused as-is, already side-neutral)
--
-- Rollback limitations: MariaDB DDL implicitly commits. Drop triggers before
-- dropping tables, and only before any row has left its initial state.

CREATE TABLE executor_execution_handoff (
    executor_execution_handoff_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    plan_source                    VARCHAR(64) NOT NULL
        COMMENT 'Upstream lane identity, e.g. AUTOMATIC_EXIT_PLAN_V1, AUTOMATIC_ENTRY_PLAN_V1, MANUAL_EXECUTION_PLAN_SNAPSHOT_V1. Not a foreign key: plan persistence is owned by the upstream lane.',
    plan_reference_id              VARCHAR(128) NOT NULL
        COMMENT 'Upstream-lane-specific identifier for the exact approved immutable plan.',
    plan_content_hash              CHAR(64) NOT NULL
        COMMENT 'sha256 hex of the canonical immutable plan payload (account/venue/market/side/legs). Binds this handoff to exact plan content, independent of any cross-schema foreign key.',

    trading_account_id             BIGINT UNSIGNED NOT NULL,
    venue                          VARCHAR(32) NOT NULL,
    market                         VARCHAR(64) NOT NULL,
    side                           VARCHAR(8) NOT NULL,

    executor_mode                  VARCHAR(16) NOT NULL
        COMMENT 'DRY_RUN | PAPER | LIVE_DISABLED. LIVE_DISABLED is never claimable at intake.',
    executor_identity               VARCHAR(128) NOT NULL,
    runtime_owner                   VARCHAR(64) NOT NULL,
    executor_credential_binding_id  BIGINT UNSIGNED NOT NULL,

    claim_state                    VARCHAR(16) NOT NULL DEFAULT 'CLAIMED'
        COMMENT 'CLAIMED | CONSUMED | FAILED. CONSUMED/FAILED are terminal.',
    claimed_ts_utc                  DATETIME(6) NOT NULL,
    consumed_ts_utc                 DATETIME(6) NULL,
    outcome_code                    VARCHAR(64) NULL,
    outcome_detail                  VARCHAR(255) NULL,
    created_ts_utc                  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (executor_execution_handoff_id),
    UNIQUE KEY uq_eeh_plan_reference (plan_source, plan_reference_id),
    KEY idx_eeh_account_venue_side (trading_account_id, venue, side),

    CONSTRAINT fk_eeh_trading_account
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_eeh_credential_binding
        FOREIGN KEY (executor_credential_binding_id)
        REFERENCES executor_credential_binding (executor_credential_binding_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,

    CONSTRAINT chk_eeh_side CHECK (side IN ('BUY', 'SELL')),
    CONSTRAINT chk_eeh_executor_mode
        CHECK (executor_mode IN ('DRY_RUN', 'PAPER', 'LIVE_DISABLED')),
    CONSTRAINT chk_eeh_claim_state
        CHECK (claim_state IN ('CLAIMED', 'CONSUMED', 'FAILED')),
    CONSTRAINT chk_eeh_content_hash_length CHECK (CHAR_LENGTH(plan_content_hash) = 64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Side-neutral immutable executor handoff identity shared by algorithmic BUY/SELL (#206). One row per (plan_source, plan_reference_id).';

CREATE TABLE executor_execution_leg (
    executor_execution_leg_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    executor_execution_handoff_id  BIGINT UNSIGNED NOT NULL,
    leg_index                      INT UNSIGNED NOT NULL,
    trading_account_id             BIGINT UNSIGNED NOT NULL,
    venue                          VARCHAR(32) NOT NULL,
    market                         VARCHAR(64) NOT NULL,
    side                           VARCHAR(8) NOT NULL,

    client_order_id                CHAR(36) NOT NULL
        COMMENT 'Deterministic UUIDv5 derived from handoff plan identity + leg_index + account/venue/market. Never random.',
    operator_id                    BIGINT UNSIGNED NOT NULL
        COMMENT 'Explicit canonical venue operatorId for the Synth executor/bot. Never inferred from display name.',

    immutable_price                DECIMAL(20,10) NOT NULL
        COMMENT 'Exact persisted execution_planner leg price. Executor never recomputes this.',
    immutable_quantity             DECIMAL(20,10) NOT NULL
        COMMENT 'Exact persisted execution_planner leg quantity. Executor never recomputes this.',

    submission_state               VARCHAR(24) NOT NULL DEFAULT 'PREPARED'
        COMMENT 'PREPARED | SUBMISSION_UNCERTAIN | RECONCILIATION_REQUIRED | ACTIVE | PARTIALLY_FILLED | FILLED | CANCELED | EXPIRED | REJECTED | FAILED',
    broker_order_id                VARCHAR(128) NULL,
    broker_status                  VARCHAR(64) NULL
        COMMENT 'Raw venue-vocabulary status string, audit-only. Never used directly as executor state.',
    attempt_started_ts_utc         DATETIME(6) NULL,
    broker_ack_ts_utc              DATETIME(6) NULL,
    last_reconciled_ts_utc         DATETIME(6) NULL,
    reconciled_by                  VARCHAR(128) NULL
        COMMENT 'Explicit operator identity for a RECONCILIATION_REQUIRED -> PREPARED rearm. Never set by automatic orchestration.',
    safe_error_code                VARCHAR(64) NULL
        COMMENT 'Normalized non-secret error classification only. Never raw broker response text.',
    created_ts_utc                 DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (executor_execution_leg_id),
    UNIQUE KEY uq_eel_handoff_leg (executor_execution_handoff_id, leg_index),
    UNIQUE KEY uq_eel_client_order_id (client_order_id),
    KEY idx_eel_account_venue (trading_account_id, venue),

    CONSTRAINT fk_eel_handoff
        FOREIGN KEY (executor_execution_handoff_id)
        REFERENCES executor_execution_handoff (executor_execution_handoff_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_eel_trading_account
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,

    CONSTRAINT chk_eel_side CHECK (side IN ('BUY', 'SELL')),
    CONSTRAINT chk_eel_submission_state CHECK (submission_state IN (
        'PREPARED', 'SUBMISSION_UNCERTAIN', 'RECONCILIATION_REQUIRED',
        'ACTIVE', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'EXPIRED',
        'REJECTED', 'FAILED'
    )),
    CONSTRAINT chk_eel_price_positive CHECK (immutable_price > 0),
    CONSTRAINT chk_eel_quantity_positive CHECK (immutable_quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='One row per (handoff, leg_index). Side-neutral per-leg crash-safe broker submission state machine shared by algorithmic BUY/SELL (#206). No secret material stored.';

CREATE TABLE executor_live_authority (
    executor_live_authority_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trading_account_id             BIGINT UNSIGNED NOT NULL,
    venue                          VARCHAR(32) NOT NULL,
    side                           VARCHAR(8) NOT NULL,
    market                         VARCHAR(64) NULL
        COMMENT 'NULL = every market for this account/venue/side. Non-NULL narrows the grant to exactly one market.',
    executor_identity              VARCHAR(128) NOT NULL,
    runtime_owner                  VARCHAR(64) NOT NULL,

    effective_from_ts_utc          DATETIME(6) NOT NULL,
    effective_until_ts_utc         DATETIME(6) NOT NULL
        COMMENT 'Mandatory bounded expiry -- LIVE authority is never open-ended.',
    revoked_ts_utc                 DATETIME(6) NULL,
    revoked_by                     VARCHAR(128) NULL,

    authorized_by                  VARCHAR(128) NOT NULL,
    authorization_reason           VARCHAR(255) NOT NULL,
    created_ts_utc                 DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (executor_live_authority_id),
    KEY idx_ela_scope (trading_account_id, venue, side, market, effective_from_ts_utc),

    CONSTRAINT fk_ela_trading_account
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,

    CONSTRAINT chk_ela_side CHECK (side IN ('BUY', 'SELL')),
    CONSTRAINT chk_ela_window CHECK (effective_until_ts_utc > effective_from_ts_utc),
    CONSTRAINT chk_ela_revocation CHECK (revoked_ts_utc IS NULL OR revoked_ts_utc >= effective_from_ts_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='P0-D: deny-by-default, account/venue/side[/market]-scoped, bounded, revocable, auditable LIVE authority. Absence = denied. Never bound to one handoff/plan.';

CREATE TABLE executor_kill_switch (
    executor_kill_switch_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    engaged                        TINYINT(1) NOT NULL,
    reason                         VARCHAR(255) NOT NULL,
    engaged_by                     VARCHAR(128) NOT NULL,
    created_ts_utc                 DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (executor_kill_switch_id),
    KEY idx_eks_created (created_ts_utc),

    CONSTRAINT chk_eks_engaged CHECK (engaged IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='P0-D: append-only global kill switch. Most recent row is authoritative. No row = not engaged (deny-by-default already comes from executor_live_authority absence).';

DELIMITER $$

CREATE TRIGGER trg_eeh_no_identity_mutation
BEFORE UPDATE ON executor_execution_handoff
FOR EACH ROW
BEGIN
    IF OLD.claim_state IN ('CONSUMED', 'FAILED') THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EXECUTOR_EXECUTION_HANDOFF_ALREADY_TERMINAL';
    END IF;
    IF NOT (
        OLD.plan_source <=> NEW.plan_source
        AND OLD.plan_reference_id <=> NEW.plan_reference_id
        AND OLD.plan_content_hash <=> NEW.plan_content_hash
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
            SET MESSAGE_TEXT = 'EXECUTOR_EXECUTION_HANDOFF_IDENTITY_IS_IMMUTABLE';
    END IF;
    IF NOT (OLD.claim_state = 'CLAIMED' AND NEW.claim_state IN ('CONSUMED', 'FAILED')) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EXECUTOR_EXECUTION_HANDOFF_INVALID_CLAIM_TRANSITION';
    END IF;
END$$

CREATE TRIGGER trg_eeh_no_delete
BEFORE DELETE ON executor_execution_handoff
FOR EACH ROW SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'EXECUTOR_EXECUTION_HANDOFF_IS_IMMUTABLE'$$

CREATE TRIGGER trg_eel_identity_immutable
BEFORE UPDATE ON executor_execution_leg
FOR EACH ROW
BEGIN
    IF NOT (
        OLD.executor_execution_handoff_id <=> NEW.executor_execution_handoff_id
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
            SET MESSAGE_TEXT = 'EXECUTOR_EXECUTION_LEG_IDENTITY_IS_IMMUTABLE';
    END IF;
    IF OLD.submission_state IN ('FILLED', 'CANCELED', 'EXPIRED', 'REJECTED', 'FAILED')
       AND NEW.submission_state <> OLD.submission_state THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EXECUTOR_EXECUTION_LEG_ALREADY_TERMINAL';
    END IF;
END$$

CREATE TRIGGER trg_eel_no_delete
BEFORE DELETE ON executor_execution_leg
FOR EACH ROW SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'EXECUTOR_EXECUTION_LEG_IS_IMMUTABLE'$$

DELIMITER ;

-- Deterministic down contract (manual, only before rows are created):
-- DROP TRIGGER trg_eel_no_delete;
-- DROP TRIGGER trg_eel_identity_immutable;
-- DROP TRIGGER trg_eeh_no_delete;
-- DROP TRIGGER trg_eeh_no_identity_mutation;
-- DROP TABLE executor_kill_switch;
-- DROP TABLE executor_live_authority;
-- DROP TABLE executor_execution_leg;
-- DROP TABLE executor_execution_handoff;
