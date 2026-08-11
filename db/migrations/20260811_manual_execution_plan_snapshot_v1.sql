-- Migration: manual_execution_plan_snapshot_v1
-- Status: CREATED BUT NOT APPLIED as of 2026-08-11.
-- Boundary: schema only; no broker calls, orders, executor writes, or live
--           enablement. Additive only.
--
-- Purpose: the immutable manual execution plan-snapshot table named as
--          missing in db/migrations/20260628_execution_ladder_profiles_v1.sql
--          ("Non-goals: ... no plan snapshot"). One row per approved manual
--          execution request, recording the exact permissioned/planning
--          inputs execution_planner used to build the ladder/plan preview
--          (src.execution_planner.contract_preview_v1), so the reason a
--          ladder was generated can be reconstructed later without
--          depending on mutable request/approval/market state. Closes
--          GitHub Issue #202.
--
-- Side-neutral: the schema accepts side IN ('BUY', 'SELL'). BUY requests
--          are still rejected upstream at decision_gate today
--          (REASON_MANUAL_BUY_GATE_NOT_YET_IMPLEMENTED in
--          src/decision_gate/manual_execution_gate_v1.py), so no BUY row
--          can be written by production code yet — that gate/quantity-
--          resolution work is a separate, not-yet-implemented step, not
--          this migration's concern.
--
-- Permission boundary: a row can only be inserted for a manual_execution_request
--          that already has a manual_execution_approval row (UNIQUE FK), and
--          manual_execution_approval itself is only ever written by
--          decision_gate.manual_execution_gate_v1.approve_and_reserve() on
--          GATE_DECISION_EXECUTION_ALLOWED — a BLOCKED/DENIED decision never
--          produces an approval row, so it can never produce a plan snapshot
--          row either (see 20260726_manual_execution_atomic_approval_v1.sql).
--
-- Deployment order:
--   1. 20260628_execution_ladder_profiles_v1.sql
--      (execution_ladder_profile already exists after this step)
--   2. 20260725_manual_execution_ladder_p0_safety_v1.sql
--   3. 20260726_manual_execution_request_v1.sql
--   4. 20260726_manual_execution_atomic_approval_v1.sql
--      (manual_execution_approval already exists after this step)
--   5. this migration
--   6. deploy execution_planner runtime that writes this table together
--
-- Compatibility window: none — this table has no prior rows and no
--          existing reader/writer to stay compatible with.
--
-- Rollback limitations:
--   MariaDB DDL implicitly commits. Dropping this table after the planner
--   runtime has issued plan snapshots destroys planning-provenance history
--   and is not a safe online rollback. Roll runtime back before any plan
--   snapshots are issued, or retain the additive schema during rollback.
--   Forward-only rollback statement (apply only before any runtime writes):
--     DROP TRIGGER IF EXISTS trg_manual_execution_plan_snapshot_no_update;
--     DROP TRIGGER IF EXISTS trg_manual_execution_plan_snapshot_no_delete;
--     DROP TABLE IF EXISTS manual_execution_plan_snapshot;

DELIMITER $$

DROP PROCEDURE IF EXISTS migrate_manual_execution_plan_snapshot_v1$$
CREATE PROCEDURE migrate_manual_execution_plan_snapshot_v1()
BEGIN
    DECLARE object_count INT DEFAULT 0;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'manual_execution_request'
      AND table_type = 'BASE TABLE';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MEPS_MANUAL_EXECUTION_REQUEST_TABLE_REQUIRED';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'manual_execution_approval'
      AND table_type = 'BASE TABLE';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MEPS_MANUAL_EXECUTION_APPROVAL_TABLE_REQUIRED';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_ladder_profile'
      AND table_type = 'BASE TABLE';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MEPS_EXECUTION_LADDER_PROFILE_TABLE_REQUIRED';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_research_provenance'
      AND table_type = 'BASE TABLE';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MEPS_EXECUTION_RESEARCH_PROVENANCE_TABLE_REQUIRED';
    END IF;
END$$

CALL migrate_manual_execution_plan_snapshot_v1()$$
DROP PROCEDURE migrate_manual_execution_plan_snapshot_v1$$

DELIMITER ;

CREATE TABLE IF NOT EXISTS manual_execution_plan_snapshot (
    manual_execution_plan_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    idempotency_key                VARCHAR(160)   NOT NULL
        COMMENT 'manual_execution_plan_snapshot:<request.idempotency_key>',
    manual_execution_request_id    BIGINT UNSIGNED NOT NULL,
    manual_execution_approval_id   BIGINT UNSIGNED NOT NULL,

    trading_account_id             BIGINT UNSIGNED NOT NULL,
    account_code                   VARCHAR(64)    NOT NULL,
    venue                          VARCHAR(32)    NOT NULL,
    asset_id                       INT(11)        NOT NULL,
    base_asset                     VARCHAR(32)    NOT NULL,
    quote_asset                    VARCHAR(16)    NOT NULL,
    side                           VARCHAR(8)     NOT NULL,
    mode                           VARCHAR(16)    NOT NULL,

    plan_type                      VARCHAR(32)    NOT NULL,
    execution_mode                 VARCHAR(16)    NOT NULL,
    plan_state                     VARCHAR(24)    NOT NULL DEFAULT 'PREVIEW_ONLY',
    sleeve_code                    VARCHAR(32)    NOT NULL,

    ladder_profile_id              BIGINT UNSIGNED DEFAULT NULL,
    ladder_profile_version         INT            DEFAULT NULL,
    anchor_reference_price         DECIMAL(20,10) DEFAULT NULL,
    anchor_ts_utc                  DATETIME(6)    DEFAULT NULL,

    provenance_id                  BIGINT UNSIGNED DEFAULT NULL,

    approved_quantity_base         DECIMAL(30,12) NOT NULL,
    total_target_fraction          DECIMAL(10,8)  NOT NULL,
    max_notional_eur               DECIMAL(20,10) DEFAULT NULL,
    reference_price_eur            DECIMAL(20,10) NOT NULL,
    best_bid_eur                   DECIMAL(20,10) NOT NULL,
    best_ask_eur                   DECIMAL(20,10) NOT NULL,
    tick_size                      DECIMAL(20,10) NOT NULL,

    source_decision_state          VARCHAR(32)    NOT NULL,
    source_decision_reason         VARCHAR(128)   NOT NULL,

    legs_json                      TEXT           NOT NULL
        COMMENT 'immutable serialized ExecutionPlanLegPreview list used to build this plan; not re-derivable from mutable state',

    created_ts_utc                 DATETIME(6)    NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (manual_execution_plan_snapshot_id),
    UNIQUE KEY uq_manual_execution_plan_snapshot_idempotency (idempotency_key),
    UNIQUE KEY uq_manual_execution_plan_snapshot_request (manual_execution_request_id),
    UNIQUE KEY uq_manual_execution_plan_snapshot_approval (manual_execution_approval_id),
    KEY idx_manual_execution_plan_snapshot_account_asset (trading_account_id, venue, asset_id),

    CONSTRAINT fk_manual_execution_plan_snapshot_request
        FOREIGN KEY (manual_execution_request_id)
        REFERENCES manual_execution_request (manual_execution_request_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_plan_snapshot_approval
        FOREIGN KEY (manual_execution_approval_id)
        REFERENCES manual_execution_approval (manual_execution_approval_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_plan_snapshot_account
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_plan_snapshot_asset
        FOREIGN KEY (asset_id)
        REFERENCES asset (asset_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_plan_snapshot_ladder_profile
        FOREIGN KEY (ladder_profile_id)
        REFERENCES execution_ladder_profile (ladder_profile_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_plan_snapshot_provenance
        FOREIGN KEY (provenance_id)
        REFERENCES execution_research_provenance (provenance_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,

    CONSTRAINT chk_manual_execution_plan_snapshot_side
        CHECK (side IN ('BUY', 'SELL')),
    CONSTRAINT chk_manual_execution_plan_snapshot_mode
        CHECK (mode = 'PAPER'),
    CONSTRAINT chk_manual_execution_plan_snapshot_state
        CHECK (plan_state = 'PREVIEW_ONLY'),
    CONSTRAINT chk_manual_execution_plan_snapshot_quantity
        CHECK (approved_quantity_base > 0),
    CONSTRAINT chk_manual_execution_plan_snapshot_fraction
        CHECK (total_target_fraction > 0)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Immutable manual execution plan snapshot: exactly one row per approved manual_execution_request, recording the ladder profile/anchor/provenance/leg inputs execution_planner used. No executor consumes this table yet; plan_state is fixed at PREVIEW_ONLY until a future, separately-authorized executor lane is added.';

DELIMITER $$

DROP TRIGGER IF EXISTS trg_manual_execution_plan_snapshot_no_update$$
CREATE TRIGGER trg_manual_execution_plan_snapshot_no_update
BEFORE UPDATE ON manual_execution_plan_snapshot
FOR EACH ROW
SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'MANUAL_EXECUTION_PLAN_SNAPSHOT_IS_IMMUTABLE'$$

DROP TRIGGER IF EXISTS trg_manual_execution_plan_snapshot_no_delete$$
CREATE TRIGGER trg_manual_execution_plan_snapshot_no_delete
BEFORE DELETE ON manual_execution_plan_snapshot
FOR EACH ROW
SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'MANUAL_EXECUTION_PLAN_SNAPSHOT_IS_IMMUTABLE'$$

DELIMITER ;
