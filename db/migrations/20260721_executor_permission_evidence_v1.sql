-- Migration: executor_permission_evidence_v2
-- Boundary: decision_gate permission -> execution_plan binding -> executor claim.
-- The obsolete execution_permission_evidence draft table is preserved for audit
-- but is never read by the v2 executor.

DELIMITER $$

DROP PROCEDURE IF EXISTS migrate_executor_permission_evidence_v2$$
CREATE PROCEDURE migrate_executor_permission_evidence_v2()
BEGIN
    DECLARE object_count INT DEFAULT 0;
    DECLARE null_count BIGINT DEFAULT 0;
    DECLARE nullable_value VARCHAR(3);

    ALTER TABLE decision_gate_audit_log
        ADD COLUMN IF NOT EXISTS market VARCHAR(32) NULL AFTER symbol;

    ALTER TABLE execution_plan
        ADD COLUMN IF NOT EXISTS market VARCHAR(32) NULL AFTER venue,
        ADD COLUMN IF NOT EXISTS execution_intent VARCHAR(64) NULL AFTER desired_action,
        ADD COLUMN IF NOT EXISTS action_type VARCHAR(64) NULL AFTER execution_intent,
        ADD COLUMN IF NOT EXISTS requested_side VARCHAR(16) NULL AFTER action_type,
        ADD COLUMN IF NOT EXISTS trading_account_id BIGINT UNSIGNED NULL AFTER account_id,
        ADD COLUMN IF NOT EXISTS decision_gate_permission_evidence_id BIGINT UNSIGNED NULL AFTER trading_account_id;

    UPDATE execution_plan
    SET execution_mode = 'PAPER'
    WHERE execution_mode = 'paper';

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND column_name = 'trading_account_id'
      AND column_type = 'bigint(20) unsigned'
      AND is_nullable = 'YES';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_EXECUTION_PLAN_TRADING_ACCOUNT_ID';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND (
          (column_name = 'decision_gate_permission_evidence_id' AND column_type = 'bigint(20) unsigned' AND is_nullable = 'YES')
          OR (column_name = 'market' AND column_type = 'varchar(32)' AND is_nullable = 'YES')
          OR (column_name = 'execution_intent' AND column_type = 'varchar(64)' AND is_nullable = 'YES')
          OR (column_name = 'action_type' AND column_type = 'varchar(64)' AND is_nullable = 'YES')
          OR (column_name = 'requested_side' AND column_type = 'varchar(16)' AND is_nullable = 'YES')
      );
    IF object_count <> 5 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_EXECUTION_PLAN_BINDING_COLUMNS';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'decision_gate_audit_log'
      AND column_name = 'market'
      AND column_type = 'varchar(32)'
      AND is_nullable = 'YES';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_AUDIT_MARKET_COLUMN';
    END IF;

    CREATE TABLE IF NOT EXISTS decision_gate_permission_evidence (
        decision_gate_permission_evidence_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        decision_gate_audit_log_id BIGINT UNSIGNED NOT NULL,
        producer_name VARCHAR(96) NOT NULL,
        provenance_signature CHAR(88) NOT NULL,
        trading_account_id BIGINT UNSIGNED NOT NULL,
        venue VARCHAR(32) NOT NULL,
        asset_id BIGINT UNSIGNED NOT NULL,
        market VARCHAR(32) NOT NULL,
        execution_intent VARCHAR(64) NOT NULL,
        action_type VARCHAR(64) NOT NULL,
        requested_side VARCHAR(16) NOT NULL,
        permission_state VARCHAR(64) NOT NULL,
        decision_state VARCHAR(64) NOT NULL,
        evidence_state VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
        permitted_ts_utc DATETIME(6) NOT NULL,
        valid_until_ts_utc DATETIME(6) NOT NULL,
        revoked_ts_utc DATETIME(6) NULL,
        superseded_by_evidence_id BIGINT UNSIGNED NULL,
        created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        PRIMARY KEY (decision_gate_permission_evidence_id)
    ) ENGINE=InnoDB
      DEFAULT CHARSET=utf8mb4
      COLLATE=utf8mb4_unicode_ci
      COMMENT='Signed decision_gate-owned permission evidence. Scope is immutable; lifecycle fields support revocation and supersession.';

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence';
    IF object_count <> 19 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_PERMISSION_TABLE_COLUMNS';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence'
      AND (
          (column_name = 'decision_gate_permission_evidence_id' AND column_type = 'bigint(20) unsigned' AND is_nullable = 'NO')
          OR (column_name = 'decision_gate_audit_log_id' AND column_type = 'bigint(20) unsigned')
          OR (column_name = 'producer_name' AND column_type = 'varchar(96)' AND is_nullable = 'NO')
          OR (column_name = 'provenance_signature' AND column_type = 'char(88)' AND is_nullable = 'NO')
          OR (column_name = 'trading_account_id' AND column_type = 'bigint(20) unsigned' AND is_nullable = 'NO')
          OR (column_name = 'asset_id' AND column_type = 'bigint(20) unsigned' AND is_nullable = 'NO')
          OR (column_name = 'permitted_ts_utc' AND column_type = 'datetime(6)' AND is_nullable = 'NO')
          OR (column_name = 'valid_until_ts_utc' AND column_type = 'datetime(6)' AND is_nullable = 'NO')
          OR (column_name = 'superseded_by_evidence_id' AND column_type = 'bigint(20) unsigned' AND is_nullable = 'YES')
      );
    IF object_count <> 9 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_PERMISSION_TABLE_TYPES';
    END IF;

    SELECT is_nullable INTO nullable_value
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence'
      AND column_name = 'decision_gate_audit_log_id';
    IF nullable_value = 'YES' THEN
        SELECT COUNT(*) INTO null_count
        FROM decision_gate_permission_evidence
        WHERE decision_gate_audit_log_id IS NULL;
        IF null_count <> 0 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'EPE_MIGRATION_NULL_AUDIT_PROVENANCE_REQUIRES_MANUAL_REPAIR';
        END IF;
        ALTER TABLE decision_gate_permission_evidence
            MODIFY decision_gate_audit_log_id BIGINT UNSIGNED NOT NULL;
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence'
      AND column_name = 'decision_gate_audit_log_id'
      AND column_type = 'bigint(20) unsigned'
      AND is_nullable = 'NO';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_AUDIT_PROVENANCE_TYPE';
    END IF;

    ALTER TABLE decision_gate_permission_evidence
        ADD UNIQUE INDEX IF NOT EXISTS uq_dgpe_audit_v2 (decision_gate_audit_log_id),
        ADD INDEX IF NOT EXISTS ix_dgpe_account_scope_v2 (
            trading_account_id, venue, asset_id, market, evidence_state
        ),
        ADD INDEX IF NOT EXISTS ix_dgpe_successor_v2 (superseded_by_evidence_id);

    SELECT COUNT(*) INTO object_count
    FROM (
        SELECT index_name, non_unique,
               GROUP_CONCAT(column_name ORDER BY seq_in_index) AS index_columns
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'decision_gate_permission_evidence'
          AND index_name IN ('uq_dgpe_audit_v2', 'ix_dgpe_account_scope_v2', 'ix_dgpe_successor_v2')
        GROUP BY index_name, non_unique
        HAVING (index_name = 'uq_dgpe_audit_v2' AND non_unique = 0 AND index_columns = 'decision_gate_audit_log_id')
            OR (index_name = 'ix_dgpe_account_scope_v2' AND index_columns = 'trading_account_id,venue,asset_id,market,evidence_state')
            OR (index_name = 'ix_dgpe_successor_v2' AND index_columns = 'superseded_by_evidence_id')
    ) AS verified_permission_indexes;
    IF object_count <> 3 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_PERMISSION_INDEXES';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence'
      AND constraint_name = 'chk_dgpe_state_v2';
    IF object_count = 0 THEN
        ALTER TABLE decision_gate_permission_evidence
            ADD CONSTRAINT chk_dgpe_state_v2
            CHECK (BINARY evidence_state IN ('ACTIVE', 'REVOKED', 'SUPERSEDED'));
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.check_constraints
    WHERE constraint_schema = DATABASE()
      AND constraint_name = 'chk_dgpe_state_v2'
      AND LOWER(check_clause) LIKE '%evidence_state%'
      AND LOWER(check_clause) LIKE '%active%'
      AND LOWER(check_clause) LIKE '%revoked%'
      AND LOWER(check_clause) LIKE '%superseded%';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_PERMISSION_STATE_CHECK';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence'
      AND constraint_name = 'chk_dgpe_scope_v2';
    IF object_count = 0 THEN
        ALTER TABLE decision_gate_permission_evidence
            ADD CONSTRAINT chk_dgpe_scope_v2
            CHECK (
                BINARY producer_name = BINARY 'decision_gate_permission_service_v1'
                AND CHAR_LENGTH(provenance_signature) = 88
                AND BINARY action_type IN ('PLACE_ORDER', 'CANCEL_ORDER', 'MONITOR_ORDER')
                AND BINARY requested_side IN ('BUY', 'SELL')
                AND BINARY permission_state = BINARY 'EXECUTION_PERMITTED'
                AND BINARY decision_state = BINARY 'EXECUTION_ALLOWED'
            );
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.check_constraints
    WHERE constraint_schema = DATABASE()
      AND constraint_name = 'chk_dgpe_scope_v2'
      AND LOWER(check_clause) LIKE '%producer_name%'
      AND LOWER(check_clause) LIKE '%requested_side%'
      AND LOWER(check_clause) LIKE '%place_order%'
      AND LOWER(check_clause) LIKE '%execution_permitted%'
      AND LOWER(check_clause) LIKE '%execution_allowed%';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_PERMISSION_SCOPE_CHECK';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence'
      AND constraint_name = 'chk_dgpe_window_v2';
    IF object_count = 0 THEN
        ALTER TABLE decision_gate_permission_evidence
            ADD CONSTRAINT chk_dgpe_window_v2
            CHECK (valid_until_ts_utc >= permitted_ts_utc);
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.check_constraints
    WHERE constraint_schema = DATABASE()
      AND constraint_name = 'chk_dgpe_window_v2'
      AND LOWER(check_clause) LIKE '%valid_until_ts_utc%'
      AND LOWER(check_clause) LIKE '%permitted_ts_utc%';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_PERMISSION_WINDOW_CHECK';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence'
      AND constraint_name = 'chk_dgpe_lifecycle_v2';
    IF object_count = 0 THEN
        ALTER TABLE decision_gate_permission_evidence
            ADD CONSTRAINT chk_dgpe_lifecycle_v2
            CHECK (
                (BINARY evidence_state = BINARY 'ACTIVE' AND revoked_ts_utc IS NULL AND superseded_by_evidence_id IS NULL)
                OR (BINARY evidence_state = BINARY 'REVOKED' AND revoked_ts_utc IS NOT NULL AND superseded_by_evidence_id IS NULL)
                OR (
                    BINARY evidence_state = BINARY 'SUPERSEDED'
                    AND revoked_ts_utc IS NULL
                    AND superseded_by_evidence_id IS NOT NULL
                )
            );
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.check_constraints
    WHERE constraint_schema = DATABASE()
      AND constraint_name = 'chk_dgpe_lifecycle_v2'
      AND LOWER(check_clause) LIKE '%revoked_ts_utc%'
      AND LOWER(check_clause) LIKE '%superseded_by_evidence_id%';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_PERMISSION_LIFECYCLE_CHECK';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence'
      AND constraint_name = 'fk_dgpe_audit_v2';
    IF object_count = 0 THEN
        ALTER TABLE decision_gate_permission_evidence
            ADD CONSTRAINT fk_dgpe_audit_v2
            FOREIGN KEY (decision_gate_audit_log_id)
            REFERENCES decision_gate_audit_log (decision_gate_audit_log_id);
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence'
      AND constraint_name = 'fk_dgpe_account_v2';
    IF object_count = 0 THEN
        ALTER TABLE decision_gate_permission_evidence
            ADD CONSTRAINT fk_dgpe_account_v2
            FOREIGN KEY (trading_account_id)
            REFERENCES trading_account (trading_account_id);
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence'
      AND constraint_name = 'fk_dgpe_successor_v2';
    IF object_count = 0 THEN
        ALTER TABLE decision_gate_permission_evidence
            ADD CONSTRAINT fk_dgpe_successor_v2
            FOREIGN KEY (superseded_by_evidence_id)
            REFERENCES decision_gate_permission_evidence (decision_gate_permission_evidence_id);
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.key_column_usage
    WHERE constraint_schema = DATABASE()
      AND table_name = 'decision_gate_permission_evidence'
      AND (
          (constraint_name = 'fk_dgpe_audit_v2' AND column_name = 'decision_gate_audit_log_id' AND referenced_table_name = 'decision_gate_audit_log' AND referenced_column_name = 'decision_gate_audit_log_id')
          OR (constraint_name = 'fk_dgpe_account_v2' AND column_name = 'trading_account_id' AND referenced_table_name = 'trading_account' AND referenced_column_name = 'trading_account_id')
          OR (constraint_name = 'fk_dgpe_successor_v2' AND column_name = 'superseded_by_evidence_id' AND referenced_table_name = 'decision_gate_permission_evidence' AND referenced_column_name = 'decision_gate_permission_evidence_id')
      );
    IF object_count <> 3 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_PERMISSION_FOREIGN_KEYS';
    END IF;

    CREATE TABLE IF NOT EXISTS execution_attempt (
        execution_attempt_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        execution_plan_id BIGINT UNSIGNED NOT NULL,
        decision_gate_permission_evidence_id BIGINT UNSIGNED NOT NULL,
        trading_account_id BIGINT UNSIGNED NOT NULL,
        action_type VARCHAR(64) NOT NULL,
        attempt_number INT UNSIGNED NOT NULL,
        claim_token CHAR(36) NOT NULL,
        claim_owner VARCHAR(128) NOT NULL,
        claimed_ts_utc DATETIME(6) NOT NULL,
        authorization_snapshot_ts_utc DATETIME(6) NOT NULL,
        idempotency_key CHAR(64) NOT NULL,
        broker_client_order_id CHAR(36) NOT NULL,
        attempt_state VARCHAR(32) NOT NULL,
        broker_order_id VARCHAR(128) NULL,
        failure_code VARCHAR(128) NULL,
        updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
        PRIMARY KEY (execution_attempt_id)
    ) ENGINE=InnoDB
      DEFAULT CHARSET=utf8mb4
      COLLATE=utf8mb4_unicode_ci
      COMMENT='Durable executor authorization-consumption claim and broker idempotency record.';

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_attempt';
    IF object_count <> 16 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_EXECUTION_ATTEMPT_COLUMNS';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_attempt'
      AND (
          (column_name = 'execution_attempt_id' AND column_type = 'bigint(20) unsigned' AND is_nullable = 'NO')
          OR (column_name = 'execution_plan_id' AND column_type = 'bigint(20) unsigned' AND is_nullable = 'NO')
          OR (column_name = 'decision_gate_permission_evidence_id' AND column_type = 'bigint(20) unsigned' AND is_nullable = 'NO')
          OR (column_name = 'trading_account_id' AND column_type = 'bigint(20) unsigned' AND is_nullable = 'NO')
          OR (column_name = 'claim_token' AND column_type = 'char(36)' AND is_nullable = 'NO')
          OR (column_name = 'idempotency_key' AND column_type = 'char(64)' AND is_nullable = 'NO')
          OR (column_name = 'broker_client_order_id' AND column_type = 'char(36)' AND is_nullable = 'NO')
      );
    IF object_count <> 7 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_EXECUTION_ATTEMPT_TYPES';
    END IF;

    ALTER TABLE execution_attempt
        ADD UNIQUE INDEX IF NOT EXISTS uq_execution_attempt_plan_action_v2 (execution_plan_id, action_type),
        ADD UNIQUE INDEX IF NOT EXISTS uq_execution_attempt_claim_token_v2 (claim_token),
        ADD UNIQUE INDEX IF NOT EXISTS uq_execution_attempt_idempotency_v2 (idempotency_key),
        ADD UNIQUE INDEX IF NOT EXISTS uq_execution_attempt_broker_client_order_v2 (broker_client_order_id);

    SELECT COUNT(*) INTO object_count
    FROM (
        SELECT index_name, non_unique,
               GROUP_CONCAT(column_name ORDER BY seq_in_index) AS index_columns
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'execution_attempt'
          AND index_name IN (
              'uq_execution_attempt_plan_action_v2',
              'uq_execution_attempt_claim_token_v2',
              'uq_execution_attempt_idempotency_v2',
              'uq_execution_attempt_broker_client_order_v2'
          )
        GROUP BY index_name, non_unique
        HAVING non_unique = 0 AND (
            (index_name = 'uq_execution_attempt_plan_action_v2' AND index_columns = 'execution_plan_id,action_type')
            OR (index_name = 'uq_execution_attempt_claim_token_v2' AND index_columns = 'claim_token')
            OR (index_name = 'uq_execution_attempt_idempotency_v2' AND index_columns = 'idempotency_key')
            OR (index_name = 'uq_execution_attempt_broker_client_order_v2' AND index_columns = 'broker_client_order_id')
        )
    ) AS verified_attempt_indexes;
    IF object_count <> 4 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_EXECUTION_ATTEMPT_INDEXES';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'execution_attempt'
      AND constraint_name = 'chk_execution_attempt_state_v2';
    IF object_count = 0 THEN
        ALTER TABLE execution_attempt
            ADD CONSTRAINT chk_execution_attempt_state_v2
            CHECK (BINARY attempt_state IN ('CLAIMED', 'CONFIRMED', 'UNCERTAIN', 'FAILED'));
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'execution_attempt'
      AND constraint_name = 'fk_execution_attempt_plan_v2';
    IF object_count = 0 THEN
        ALTER TABLE execution_attempt
            ADD CONSTRAINT fk_execution_attempt_plan_v2
            FOREIGN KEY (execution_plan_id) REFERENCES execution_plan (execution_plan_id);
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'execution_attempt'
      AND constraint_name = 'fk_execution_attempt_permission_v2';
    IF object_count = 0 THEN
        ALTER TABLE execution_attempt
            ADD CONSTRAINT fk_execution_attempt_permission_v2
            FOREIGN KEY (decision_gate_permission_evidence_id)
            REFERENCES decision_gate_permission_evidence (decision_gate_permission_evidence_id);
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'execution_attempt'
      AND constraint_name = 'fk_execution_attempt_account_v2';
    IF object_count = 0 THEN
        ALTER TABLE execution_attempt
            ADD CONSTRAINT fk_execution_attempt_account_v2
            FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id);
    END IF;

    ALTER TABLE execution_plan
        ADD UNIQUE INDEX IF NOT EXISTS uq_execution_plan_permission_v2 (decision_gate_permission_evidence_id),
        ADD INDEX IF NOT EXISTS ix_execution_plan_trading_account_v2 (trading_account_id);

    SELECT COUNT(*) INTO object_count
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND index_name = 'uq_execution_plan_permission_v2'
      AND column_name = 'decision_gate_permission_evidence_id'
      AND seq_in_index = 1
      AND non_unique = 0;
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_PLAN_PERMISSION_INDEX';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM (
        SELECT index_name, GROUP_CONCAT(column_name ORDER BY seq_in_index) AS index_columns
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'execution_attempt'
          AND index_name = 'uq_execution_attempt_plan_action_v2'
        GROUP BY index_name
        HAVING index_columns = 'execution_plan_id,action_type'
    ) AS verified_claim_index;
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_CLAIM_UNIQUENESS_INDEX';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND constraint_name = 'fk_execution_plan_trading_account_v2';
    IF object_count = 0 THEN
        ALTER TABLE execution_plan
            ADD CONSTRAINT fk_execution_plan_trading_account_v2
            FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id);
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND constraint_name = 'fk_execution_plan_permission_v2';
    IF object_count = 0 THEN
        ALTER TABLE execution_plan
            ADD CONSTRAINT fk_execution_plan_permission_v2
            FOREIGN KEY (decision_gate_permission_evidence_id)
            REFERENCES decision_gate_permission_evidence (decision_gate_permission_evidence_id);
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.key_column_usage
    WHERE constraint_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND constraint_name = 'fk_execution_plan_permission_v2'
      AND column_name = 'decision_gate_permission_evidence_id'
      AND referenced_table_name = 'decision_gate_permission_evidence'
      AND referenced_column_name = 'decision_gate_permission_evidence_id';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPE_MIGRATION_INCOMPATIBLE_PLAN_PERMISSION_FOREIGN_KEY';
    END IF;
END$$

CALL migrate_executor_permission_evidence_v2()$$
DROP PROCEDURE migrate_executor_permission_evidence_v2$$

DELIMITER ;
