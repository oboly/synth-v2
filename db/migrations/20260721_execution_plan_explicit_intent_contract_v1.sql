-- Migration: execution_plan_explicit_intent_contract_v1
-- Boundary: persisted planner contract only. Live execution remains unavailable.

DELIMITER $$

DROP PROCEDURE IF EXISTS migrate_execution_plan_explicit_intent_contract_v1$$
CREATE PROCEDURE migrate_execution_plan_explicit_intent_contract_v1()
BEGIN
    DECLARE object_count INT DEFAULT 0;
    DECLARE exact_count INT DEFAULT 0;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND table_type = 'BASE TABLE';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPC_MIGRATION_EXECUTION_PLAN_TABLE_REQUIRED';
    END IF;

    ALTER TABLE execution_plan
        ADD COLUMN IF NOT EXISTS trading_account_id BIGINT UNSIGNED NULL AFTER account_id,
        ADD COLUMN IF NOT EXISTS market VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL AFTER venue,
        ADD COLUMN IF NOT EXISTS execution_intent VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL AFTER desired_action,
        ADD COLUMN IF NOT EXISTS action_type VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL AFTER execution_intent,
        ADD COLUMN IF NOT EXISTS requested_side VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL AFTER action_type;

    UPDATE execution_plan SET execution_mode = 'PAPER' WHERE BINARY execution_mode = 'paper';
    UPDATE execution_plan SET execution_mode = 'LIVE' WHERE BINARY execution_mode = 'live';

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND column_name = 'trading_account_id'
      AND data_type = 'bigint'
      AND column_type IN ('bigint(20) unsigned', 'bigint unsigned')
      AND is_nullable = 'YES'
      AND (column_default IS NULL OR UPPER(column_default) = 'NULL');
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPC_MIGRATION_INCOMPATIBLE_TRADING_ACCOUNT_ID';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND column_name = 'market'
      AND data_type = 'varchar'
      AND character_maximum_length = 32
      AND is_nullable = 'YES'
      AND (column_default IS NULL OR UPPER(column_default) = 'NULL')
      AND character_set_name = 'utf8mb4'
      AND collation_name = 'utf8mb4_bin';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPC_MIGRATION_INCOMPATIBLE_MARKET';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND column_name = 'execution_intent'
      AND data_type = 'varchar'
      AND character_maximum_length = 64
      AND is_nullable = 'YES'
      AND (column_default IS NULL OR UPPER(column_default) = 'NULL')
      AND character_set_name = 'utf8mb4'
      AND collation_name = 'utf8mb4_bin';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPC_MIGRATION_INCOMPATIBLE_EXECUTION_INTENT';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND column_name = 'action_type'
      AND data_type = 'varchar'
      AND character_maximum_length = 64
      AND is_nullable = 'YES'
      AND (column_default IS NULL OR UPPER(column_default) = 'NULL')
      AND character_set_name = 'utf8mb4'
      AND collation_name = 'utf8mb4_bin';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPC_MIGRATION_INCOMPATIBLE_ACTION_TYPE';
    END IF;

    SELECT COUNT(*) INTO object_count
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND column_name = 'requested_side'
      AND data_type = 'varchar'
      AND character_maximum_length = 16
      AND is_nullable = 'YES'
      AND (column_default IS NULL OR UPPER(column_default) = 'NULL')
      AND character_set_name = 'utf8mb4'
      AND collation_name = 'utf8mb4_bin';
    IF object_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPC_MIGRATION_INCOMPATIBLE_REQUESTED_SIDE';
    END IF;

    SELECT COUNT(DISTINCT constraint_name) INTO object_count
    FROM information_schema.key_column_usage
    WHERE table_schema = DATABASE()
      AND table_name = 'execution_plan'
      AND column_name = 'trading_account_id'
      AND referenced_table_name IS NOT NULL;
    SELECT COUNT(*) INTO exact_count
    FROM (
        SELECT kcu.constraint_name
        FROM information_schema.key_column_usage AS kcu
        JOIN information_schema.referential_constraints AS rc
          ON rc.constraint_schema = kcu.constraint_schema
         AND rc.constraint_name = kcu.constraint_name
         AND rc.table_name = kcu.table_name
        WHERE kcu.table_schema = DATABASE()
          AND kcu.table_name = 'execution_plan'
          AND kcu.referenced_table_name IS NOT NULL
          AND kcu.constraint_name IN (
              SELECT involving.constraint_name
              FROM information_schema.key_column_usage AS involving
              WHERE involving.table_schema = DATABASE()
                AND involving.table_name = 'execution_plan'
                AND involving.column_name = 'trading_account_id'
                AND involving.referenced_table_name IS NOT NULL
          )
        GROUP BY kcu.constraint_schema, kcu.table_name, kcu.constraint_name
        HAVING COUNT(*) = 1
           AND SUM(
               kcu.column_name = 'trading_account_id'
               AND kcu.referenced_table_schema = DATABASE()
               AND kcu.referenced_table_name = 'trading_account'
               AND kcu.referenced_column_name = 'trading_account_id'
               AND kcu.ordinal_position = 1
               AND kcu.position_in_unique_constraint = 1
           ) = 1
           AND MAX(rc.update_rule) = 'RESTRICT'
           AND MAX(rc.delete_rule) = 'RESTRICT'
    ) AS exact_fk_definitions;
    IF object_count = 0 THEN
        ALTER TABLE execution_plan
            ADD CONSTRAINT fk_execution_plan_trading_account_contract_v1
            FOREIGN KEY (trading_account_id)
            REFERENCES trading_account (trading_account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT;
    ELSEIF object_count <> 1 OR exact_count <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'EPC_MIGRATION_INCOMPATIBLE_TRADING_ACCOUNT_FK';
    END IF;
END$$

CALL migrate_execution_plan_explicit_intent_contract_v1()$$
DROP PROCEDURE migrate_execution_plan_explicit_intent_contract_v1$$

DELIMITER ;
