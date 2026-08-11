-- Migration: manual_execution_plan_snapshot_idempotency_v1
-- Boundary: pre-production schema contract completion only.  Do not apply to
-- production in this PR. The one replaced legacy unique index is required so
-- a genuinely new nonce is not collapsed into a prior request.
-- Prerequisites: 20260726_manual_execution_request_v1.sql and
-- 20260726_manual_execution_atomic_approval_v1.sql.
-- Rollback: roll runtime back first; then execute the explicit DROP TRIGGER /
-- DROP TABLE / DROP FOREIGN KEY statements below only if no snapshot row exists.

ALTER TABLE manual_execution_request
    DROP INDEX uq_manual_execution_request_idempotency,
    ADD COLUMN operator_request_nonce VARCHAR(128) NULL AFTER idempotency_key,
    ADD COLUMN dedupe_key CHAR(64) NULL AFTER operator_request_nonce,
    ADD COLUMN ladder_profile_id BIGINT UNSIGNED NULL AFTER provenance_id,
    ADD COLUMN ladder_profile_version INT UNSIGNED NULL AFTER ladder_profile_id,
    ADD COLUMN anchor_type VARCHAR(64) NULL AFTER ladder_profile_version,
    ADD COLUMN anchor_price DECIMAL(30,12) NULL AFTER anchor_type,
    ADD COLUMN anchor_source VARCHAR(128) NULL AFTER anchor_price,
    ADD COLUMN source_map_cycle_id VARCHAR(128) NULL AFTER anchor_source,
    ADD COLUMN source_native_map_id VARCHAR(255) NULL AFTER source_map_cycle_id,
    ADD COLUMN source_map_version VARCHAR(64) NULL AFTER source_native_map_id,
    ADD UNIQUE KEY uq_manual_execution_request_dedupe_key (dedupe_key),
    ADD CONSTRAINT fk_manual_execution_request_ladder_profile_v1
        FOREIGN KEY (ladder_profile_id)
        REFERENCES execution_ladder_profile (ladder_profile_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE TABLE manual_execution_plan_snapshot (
    manual_execution_plan_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    manual_execution_request_id BIGINT UNSIGNED NOT NULL,
    manual_execution_approval_id BIGINT UNSIGNED NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    ladder_profile_id BIGINT UNSIGNED NOT NULL,
    ladder_profile_version INT UNSIGNED NOT NULL,
    anchor_type VARCHAR(64) NOT NULL,
    anchor_price DECIMAL(30,12) NOT NULL,
    anchor_source VARCHAR(128) NOT NULL,
    source_map_cycle_id VARCHAR(128) NOT NULL,
    source_native_map_id VARCHAR(255) NOT NULL,
    source_map_version VARCHAR(64) NOT NULL,
    provenance_id BIGINT UNSIGNED NOT NULL,
    market VARCHAR(64) NOT NULL,
    side VARCHAR(8) NOT NULL,
    quantity_policy VARCHAR(32) NOT NULL,
    approved_quantity_base DECIMAL(30,12) NOT NULL,
    planner_version VARCHAR(128) NOT NULL,
    payload_json LONGTEXT NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (manual_execution_plan_snapshot_id),
    UNIQUE KEY uq_manual_execution_plan_snapshot_request (manual_execution_request_id),
    UNIQUE KEY uq_manual_execution_plan_snapshot_approval (manual_execution_approval_id),
    CONSTRAINT fk_manual_execution_plan_snapshot_request
        FOREIGN KEY (manual_execution_request_id)
        REFERENCES manual_execution_request (manual_execution_request_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_plan_snapshot_approval
        FOREIGN KEY (manual_execution_approval_id)
        REFERENCES manual_execution_approval (manual_execution_approval_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_plan_snapshot_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_plan_snapshot_profile
        FOREIGN KEY (ladder_profile_id) REFERENCES execution_ladder_profile (ladder_profile_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_manual_execution_plan_snapshot_provenance
        FOREIGN KEY (provenance_id) REFERENCES execution_research_provenance (provenance_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT chk_manual_execution_plan_snapshot_side CHECK (side = 'SELL'),
    CONSTRAINT chk_manual_execution_plan_snapshot_quantity CHECK (approved_quantity_base > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Immutable canonical manual execution intent. No broker order/fill/cancel state is stored here.';

DELIMITER $$
CREATE TRIGGER trg_manual_execution_plan_snapshot_no_update
BEFORE UPDATE ON manual_execution_plan_snapshot
FOR EACH ROW SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'MANUAL_EXECUTION_PLAN_SNAPSHOT_IS_IMMUTABLE'$$
CREATE TRIGGER trg_manual_execution_plan_snapshot_no_delete
BEFORE DELETE ON manual_execution_plan_snapshot
FOR EACH ROW SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'MANUAL_EXECUTION_PLAN_SNAPSHOT_IS_IMMUTABLE'$$
DELIMITER ;

-- Deterministic down contract (manual, only before rows are created):
-- DROP TRIGGER trg_manual_execution_plan_snapshot_no_delete;
-- DROP TRIGGER trg_manual_execution_plan_snapshot_no_update;
-- DROP TABLE manual_execution_plan_snapshot;
-- ALTER TABLE manual_execution_request
--   DROP FOREIGN KEY fk_manual_execution_request_ladder_profile_v1,
--   DROP INDEX uq_manual_execution_request_dedupe_key,
--   ADD UNIQUE KEY uq_manual_execution_request_idempotency (idempotency_key),
--   DROP COLUMN source_map_version, DROP COLUMN source_native_map_id,
--   DROP COLUMN source_map_cycle_id, DROP COLUMN anchor_source,
--   DROP COLUMN anchor_price, DROP COLUMN anchor_type,
--   DROP COLUMN ladder_profile_version, DROP COLUMN ladder_profile_id,
--   DROP COLUMN dedupe_key, DROP COLUMN operator_request_nonce;
