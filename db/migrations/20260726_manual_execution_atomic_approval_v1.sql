-- Migration: manual_execution_atomic_approval_v1
-- Status: CREATED BUT NOT APPLIED as of 2026-07-26.
-- Boundary: schema only; no broker calls, orders, or live enablement.
--
-- Deployment order:
--   1. 20260725_manual_execution_ladder_p0_safety_v1.sql
--      (account_position_snapshot, execution_sell_reservation,
--       execution_research_provenance already exist after this step)
--   2. 20260726_manual_execution_request_v1.sql
--   3. this migration
--   4. deploy decision_gate/planner runtime together
--
-- Compatibility window:
--   Existing legacy reservation rows may have a NULL
--   manual_execution_request_id and remain readable. New manual execution
--   reservations always carry a request ID. The FK permits NULL but rejects
--   a non-NULL unknown request. The new planner reads only joined canonical
--   approval rows, so legacy rows cannot become authority.
--
-- Rollback limitations:
--   MariaDB DDL implicitly commits. Dropping this table/triggers/FK after the
--   new runtime has issued approvals destroys approval authority and is not a
--   safe online rollback. Roll runtime back before any approvals are issued,
--   or retain the additive schema during rollback. Do not delete lock rows.

DELIMITER $$

DROP PROCEDURE IF EXISTS migrate_manual_execution_atomic_approval_v1$$
CREATE PROCEDURE migrate_manual_execution_atomic_approval_v1()
BEGIN
    DECLARE object_count INT DEFAULT 0;
    DECLARE exact_count INT DEFAULT 0;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'manual_execution_request'
      AND table_type = 'BASE TABLE';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MEA_MANUAL_EXECUTION_REQUEST_TABLE_REQUIRED';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_sell_reservation'
      AND table_type = 'BASE TABLE';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MEA_EXECUTION_SELL_RESERVATION_TABLE_REQUIRED';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_research_provenance'
      AND table_type = 'BASE TABLE';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MEA_EXECUTION_RESEARCH_PROVENANCE_TABLE_REQUIRED';
    END IF;

    SELECT COUNT(DISTINCT constraint_name) INTO object_count
    FROM information_schema.key_column_usage
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_sell_reservation'
      AND column_name = 'manual_execution_request_id'
      AND referenced_table_name IS NOT NULL;
    SELECT COUNT(*) INTO exact_count
    FROM information_schema.key_column_usage AS kcu
    INNER JOIN information_schema.referential_constraints AS rc
        ON rc.constraint_schema = kcu.constraint_schema
       AND rc.table_name = kcu.table_name
       AND rc.constraint_name = kcu.constraint_name
    WHERE kcu.table_schema = DATABASE()
      AND kcu.table_name = 'execution_sell_reservation'
      AND kcu.column_name = 'manual_execution_request_id'
      AND kcu.referenced_table_name = 'manual_execution_request'
      AND kcu.referenced_column_name = 'manual_execution_request_id'
      AND rc.update_rule = 'RESTRICT'
      AND rc.delete_rule = 'RESTRICT';
    IF object_count = 0 THEN
        ALTER TABLE execution_sell_reservation
            ADD CONSTRAINT fk_execution_sell_reservation_manual_request_v1
            FOREIGN KEY (manual_execution_request_id)
            REFERENCES manual_execution_request (manual_execution_request_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT;
    ELSEIF object_count <> 1 OR exact_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MEA_INCOMPATIBLE_RESERVATION_REQUEST_FK';
    END IF;

    SELECT COUNT(DISTINCT constraint_name) INTO object_count
    FROM information_schema.key_column_usage
    WHERE table_schema = DATABASE()
      AND table_name = 'manual_execution_request'
      AND column_name = 'provenance_id'
      AND referenced_table_name IS NOT NULL;
    SELECT COUNT(*) INTO exact_count
    FROM information_schema.key_column_usage AS kcu
    INNER JOIN information_schema.referential_constraints AS rc
        ON rc.constraint_schema = kcu.constraint_schema
       AND rc.table_name = kcu.table_name
       AND rc.constraint_name = kcu.constraint_name
    WHERE kcu.table_schema = DATABASE()
      AND kcu.table_name = 'manual_execution_request'
      AND kcu.column_name = 'provenance_id'
      AND kcu.referenced_table_name = 'execution_research_provenance'
      AND kcu.referenced_column_name = 'provenance_id'
      AND rc.update_rule = 'RESTRICT'
      AND rc.delete_rule = 'RESTRICT';
    IF object_count = 0 THEN
        ALTER TABLE manual_execution_request
            ADD CONSTRAINT fk_manual_execution_request_provenance_v1
            FOREIGN KEY (provenance_id)
            REFERENCES execution_research_provenance (provenance_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT;
    ELSEIF object_count <> 1 OR exact_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'MEA_INCOMPATIBLE_REQUEST_PROVENANCE_FK';
    END IF;
END$$

CALL migrate_manual_execution_atomic_approval_v1()$$
DROP PROCEDURE migrate_manual_execution_atomic_approval_v1$$

DELIMITER ;

CREATE TABLE IF NOT EXISTS manual_execution_sell_lock (
    trading_account_id   BIGINT UNSIGNED NOT NULL,
    venue                VARCHAR(32)     NOT NULL,
    asset_id             INT(11)        NOT NULL,
    created_ts_utc       DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (trading_account_id, venue, asset_id),
    CONSTRAINT fk_manual_execution_sell_lock_account
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_sell_lock_asset
        FOREIGN KEY (asset_id)
        REFERENCES asset (asset_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Permanent lock keys for atomic manual SELL availability, reservation, and approval creation.';

CREATE TABLE IF NOT EXISTS manual_execution_approval (
    manual_execution_approval_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    idempotency_key               VARCHAR(128) NOT NULL,
    manual_execution_request_id   BIGINT UNSIGNED NOT NULL,

    trading_account_id            BIGINT UNSIGNED NOT NULL,
    account_code                  VARCHAR(64) NOT NULL,
    venue                         VARCHAR(32) NOT NULL,
    asset_id                      INT(11) NOT NULL,
    base_asset                    VARCHAR(32) NOT NULL,
    quote_asset                   VARCHAR(16) NOT NULL,
    side                          VARCHAR(8) NOT NULL,

    approved_quantity_base        DECIMAL(30,12) NOT NULL,
    wallet_snapshot_id            BIGINT UNSIGNED NOT NULL,
    wallet_snapshot_version_ts_utc DATETIME(6) NOT NULL,
    reservation_id                BIGINT UNSIGNED NOT NULL,

    approved_ts_utc               DATETIME(6) NOT NULL,
    expires_ts_utc                DATETIME(6) NOT NULL,
    mode                          VARCHAR(16) NOT NULL,
    provenance_id                 BIGINT UNSIGNED NOT NULL,
    approval_state                VARCHAR(24) NOT NULL,
    decision_reason               VARCHAR(64) NOT NULL,
    created_ts_utc                DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (manual_execution_approval_id),
    UNIQUE KEY uq_manual_execution_approval_idempotency (idempotency_key),
    UNIQUE KEY uq_manual_execution_approval_request (manual_execution_request_id),
    UNIQUE KEY uq_manual_execution_approval_reservation (reservation_id),
    KEY idx_manual_execution_approval_expiry_state (approval_state, expires_ts_utc),

    CONSTRAINT fk_manual_execution_approval_request
        FOREIGN KEY (manual_execution_request_id)
        REFERENCES manual_execution_request (manual_execution_request_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_approval_account
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_approval_asset
        FOREIGN KEY (asset_id)
        REFERENCES asset (asset_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_approval_snapshot
        FOREIGN KEY (wallet_snapshot_id)
        REFERENCES account_position_snapshot (account_position_snapshot_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_approval_reservation
        FOREIGN KEY (reservation_id)
        REFERENCES execution_sell_reservation (reservation_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_approval_provenance
        FOREIGN KEY (provenance_id)
        REFERENCES execution_research_provenance (provenance_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,

    CONSTRAINT chk_manual_execution_approval_side
        CHECK (side = 'SELL'),
    CONSTRAINT chk_manual_execution_approval_mode
        CHECK (mode = 'PAPER'),
    CONSTRAINT chk_manual_execution_approval_state
        CHECK (approval_state = 'APPROVED'),
    CONSTRAINT chk_manual_execution_approval_quantity
        CHECK (approved_quantity_base > 0),
    CONSTRAINT chk_manual_execution_approval_expiry
        CHECK (expires_ts_utc > approved_ts_utc)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Immutable decision_gate-issued manual SELL approval. Planner resolves by ID and validates joined request, reservation, snapshot, and provenance bindings.';

DELIMITER $$

DROP TRIGGER IF EXISTS trg_manual_execution_approval_no_update$$
CREATE TRIGGER trg_manual_execution_approval_no_update
BEFORE UPDATE ON manual_execution_approval
FOR EACH ROW
SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'MANUAL_EXECUTION_APPROVAL_IS_IMMUTABLE'$$

DROP TRIGGER IF EXISTS trg_manual_execution_approval_no_delete$$
CREATE TRIGGER trg_manual_execution_approval_no_delete
BEFORE DELETE ON manual_execution_approval
FOR EACH ROW
SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'MANUAL_EXECUTION_APPROVAL_IS_IMMUTABLE'$$

DELIMITER ;
