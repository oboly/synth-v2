-- Migration: native_short_scope_administration_v1
-- Boundary: Native SHORT market-data administration contracts only
-- Purpose:
--   1. Keep native_short_map_scope_v1 as the sole canonical scope identity and
--      add its nullable, forward-only support administration generation.
--   2. Add one attributable operation ledger for future ADOPT/PROMOTE/REMOVE
--      transactions without performing any operation in this migration.
--   3. Link future support and cadence history to explicit operations and
--      enforce at most one active cadence row per exact canonical scope.
-- Legacy treatment:
--   Existing NULL administration fields mean LEGACY_UNADOPTED or
--   LEGACY_UNATTRIBUTED. No historical value is inferred or backfilled.
-- Non-goals:
--   - no scope adoption, promotion, removal, map generation, or projection work
--   - no writer selection or commit-time fencing implementation
--   - no account, broker, selection, decision, planning, execution, or reporting work
-- Application contract (forward-only, single-application):
--   This migration is forward-only and single-application, matching the Native
--   SHORT schema-family convention: CREATE TABLE statements are idempotent via
--   IF NOT EXISTS, while ALTER TABLE ADD COLUMN / ADD CONSTRAINT / DROP INDEX
--   statements are not re-runnable (siblings 20260707 and 20260716 behave the
--   same way). A second application against an already-migrated schema fails
--   loudly (duplicate column / duplicate key) rather than silently corrupting;
--   this is the intended guard against accidental reapplication and is proven by
--   the migration integration test. No migration-runner state table is
--   introduced here.
-- Permanent cadence uniqueness invariant:
--   Legacy/unmanaged cadence rows carry support_generation=NULL. To keep NULL
--   support_generation from defeating uniqueness (MariaDB treats NULLs as
--   distinct in a UNIQUE key), a generated effective_generation_slot column maps
--   NULL to the reserved legacy sentinel 0 (positive managed generations can
--   never collide with it), and the profile-generation UNIQUE key is enforced on
--   the slot. This permanently forbids duplicate legacy rows for one exact scope
--   and cadence profile while still allowing distinct positive managed
--   generations of the same profile.

-- Fail before persistent DDL when legacy cadence state is not coherent enough
-- for the accepted constraints. The guard is connection-local and disappears
-- on failure, so a rejected preflight leaves persistent schema and data intact.
CREATE TEMPORARY TABLE native_short_scope_admin_preflight_v1 (
    failure_count BIGINT UNSIGNED NOT NULL,
    CONSTRAINT chk_native_short_scope_admin_preflight_v1_zero
        CHECK (failure_count = 0)
) ENGINE=MEMORY;

INSERT INTO native_short_scope_admin_preflight_v1 (failure_count)
SELECT COUNT(*)
FROM (
    SELECT
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval
    FROM native_short_scope_cadence_config_v1
    WHERE is_active = 1
    GROUP BY
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval
    HAVING COUNT(*) > 1
) duplicate_active_cadence_scopes;

INSERT INTO native_short_scope_admin_preflight_v1 (failure_count)
SELECT COUNT(*)
FROM native_short_scope_cadence_config_v1
WHERE is_active NOT IN (0, 1)
   OR (is_active = 1 AND effective_to_utc IS NOT NULL);

INSERT INTO native_short_scope_admin_preflight_v1 (failure_count)
SELECT COUNT(*)
FROM native_short_scope_cadence_config_v1 earlier
JOIN native_short_scope_cadence_config_v1 later
  ON later.cadence_config_id > earlier.cadence_config_id
 AND later.venue = earlier.venue
 AND later.symbol = earlier.symbol
 AND later.quote_currency = earlier.quote_currency
 AND later.fib_trading_horizon = earlier.fib_trading_horizon
 AND later.primary_interval = earlier.primary_interval
 AND later.supporting_interval = earlier.supporting_interval
 AND earlier.effective_from_utc < COALESCE(
        later.effective_to_utc,
        TIMESTAMP('9999-12-31 23:59:59.999999')
     )
 AND later.effective_from_utc < COALESCE(
        earlier.effective_to_utc,
        TIMESTAMP('9999-12-31 23:59:59.999999')
     );

-- Permanent legacy-duplicate invariant: at migration time every existing cadence
-- row is legacy (no support_generation), so the reserved legacy slot must hold at
-- most one row per exact scope and cadence profile. Fail before persistent DDL if
-- current data already contains duplicate legacy (scope + cadence_contract_version)
-- rows, which the replacement slot-based UNIQUE key would otherwise be unable to
-- represent for the pre-existing population.
INSERT INTO native_short_scope_admin_preflight_v1 (failure_count)
SELECT COUNT(*)
FROM (
    SELECT
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        cadence_contract_version
    FROM native_short_scope_cadence_config_v1
    GROUP BY
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        cadence_contract_version
    HAVING COUNT(*) > 1
) duplicate_legacy_cadence_profiles;

DROP TEMPORARY TABLE native_short_scope_admin_preflight_v1;


CREATE TABLE IF NOT EXISTS native_short_scope_admin_operation_v1 (
    scope_admin_operation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    operation_uuid CHAR(36) NOT NULL,
    operation_type VARCHAR(32) NOT NULL,

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL,
    fib_trading_horizon VARCHAR(32) NOT NULL,
    primary_interval    VARCHAR(16) NOT NULL,
    supporting_interval VARCHAR(16) NOT NULL,

    actor_type VARCHAR(32) NOT NULL,
    actor_id VARCHAR(128) NOT NULL,
    trigger_type VARCHAR(32) NOT NULL,
    request_source VARCHAR(160) NOT NULL,
    reason VARCHAR(255) NOT NULL,
    requested_at_utc DATETIME(6) NOT NULL,
    repository_sha CHAR(40) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    metadata_digest CHAR(64) NOT NULL
        COMMENT 'SHA-256 of the complete canonical immutable request identity',
    started_at_utc DATETIME(6) NOT NULL,
    completed_at_utc DATETIME(6) NULL,
    result_class VARCHAR(32) NULL,
    result_code VARCHAR(64) NULL,
    support_generation_before BIGINT UNSIGNED NULL,
    support_generation_after BIGINT UNSIGNED NULL,

    UNIQUE KEY uq_native_short_scope_admin_operation_v1_uuid (operation_uuid),
    -- Scope-bound composite candidate key: FK target that binds any referencing
    -- support/cadence row to this operation's immutable canonical scope snapshot,
    -- preventing cross-scope attribution structurally rather than by convention.
    UNIQUE KEY uq_native_short_scope_admin_operation_v1_id_scope (
        scope_admin_operation_id,
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval
    ),
    KEY idx_native_short_scope_admin_operation_v1_scope_started (
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        started_at_utc,
        scope_admin_operation_id
    ),
    KEY idx_native_short_scope_admin_operation_v1_result (
        result_class, completed_at_utc
    ),

    CONSTRAINT chk_native_short_scope_admin_operation_v1_uuid
        CHECK (operation_uuid REGEXP '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_type
        CHECK (operation_type IN (
            'ADOPT_LEGACY_SCOPE',
            'PROMOTE_SCOPE',
            'REMOVE_SCOPE'
        )),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_scope
        CHECK (
            BINARY venue = BINARY 'bitvavo'
            AND BINARY symbol REGEXP BINARY '^[A-Z0-9]+$'
            AND BINARY quote_currency = BINARY 'EUR'
            AND BINARY fib_trading_horizon = BINARY 'SHORT'
            AND BINARY primary_interval = BINARY '4h'
            AND BINARY supporting_interval = BINARY '1h'
        ),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_actor
        CHECK (actor_type IN ('HUMAN_OPERATOR', 'SERVICE_PRINCIPAL', 'TEST')),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_trigger
        CHECK (trigger_type IN ('MANUAL_CLI', 'AUTOMATION', 'TEST')),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_test_provenance
        CHECK (
            (actor_type = 'TEST' AND trigger_type = 'TEST')
            OR (actor_type <> 'TEST' AND trigger_type <> 'TEST')
        ),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_required_text
        CHECK (
            CHAR_LENGTH(TRIM(actor_id)) > 0
            AND CHAR_LENGTH(TRIM(request_source)) > 0
            AND CHAR_LENGTH(TRIM(reason)) > 0
            AND CHAR_LENGTH(TRIM(schema_version)) > 0
        ),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_repository_sha
        CHECK (repository_sha REGEXP '^[0-9a-f]{40}$'),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_digest
        CHECK (metadata_digest REGEXP '^[0-9a-f]{64}$'),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_result_class
        CHECK (result_class IS NULL OR result_class IN (
            'SUCCESS',
            'IDEMPOTENT_SUCCESS',
            'CONFLICT',
            'BLOCKED',
            'CORRUPT_STATE',
            'RETRYABLE'
        )),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_result_code
        CHECK (result_code IS NULL OR result_code IN (
            'ADOPTED_LEGACY_SCOPE',
            'PROMOTED_NEW_SCOPE',
            'PROMOTED_FROM_PRIOR_WITHDRAWAL',
            'REMOVED_SCOPE',
            'OPERATION_ALREADY_COMPLETED',
            'SCOPE_ALREADY_ADOPTED',
            'SCOPE_ALREADY_SUPPORTED',
            'SCOPE_ALREADY_REMOVED',
            'ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED',
            'OPERATION_METADATA_MISMATCH',
            'LEGACY_SCOPE_REQUIRES_ADOPTION',
            'CADENCE_PROFILE_CONFLICT',
            'LEGACY_ADOPTION_NOT_AUTHORIZED',
            'GLOBAL_BLOCKERS_ACTIVE',
            'LEGACY_STATE_INCOHERENT',
            'PARTIAL_SCOPE_STATE',
            'AUTHORITATIVE_WITHDRAWAL_STATE_INCOHERENT',
            'MULTIPLE_ACTIVE_CADENCE_ROWS',
            'SUPPORT_GENERATION_MISMATCH',
            'DEADLOCK',
            'LOCK_TIMEOUT',
            'COMMIT_STATUS_UNKNOWN'
        )),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_terminal
        CHECK (
            (
                completed_at_utc IS NULL
                AND result_class IS NULL
                AND result_code IS NULL
            )
            OR (
                completed_at_utc IS NOT NULL
                AND result_class IS NOT NULL
                AND result_code IS NOT NULL
            )
        ),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_timestamps
        CHECK (
            started_at_utc >= requested_at_utc
            AND (completed_at_utc IS NULL OR completed_at_utc >= started_at_utc)
        ),
    CONSTRAINT chk_native_short_scope_admin_operation_v1_generation
        CHECK (
            (support_generation_before IS NULL OR support_generation_before > 0)
            AND (support_generation_after IS NULL OR support_generation_after > 0)
            AND (
                support_generation_before IS NULL
                OR support_generation_after IS NULL
                OR support_generation_after >= support_generation_before
            )
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Typed idempotency, provenance, and terminal-result ledger for exact one-scope Native SHORT administration.';


ALTER TABLE native_short_map_scope_v1
    ADD COLUMN support_generation BIGINT UNSIGNED NULL AFTER scope_support_state,
    ADD CONSTRAINT chk_native_short_map_scope_v1_support_generation
        CHECK (support_generation IS NULL OR support_generation > 0);


ALTER TABLE native_short_scope_support_event_v1
    ADD COLUMN scope_admin_operation_id BIGINT UNSIGNED NULL AFTER scope_support_state,
    ADD COLUMN support_generation BIGINT UNSIGNED NULL AFTER scope_admin_operation_id,
    ADD UNIQUE KEY uq_native_short_scope_support_event_v1_scope_generation (
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        support_generation
    ),
    ADD UNIQUE KEY uq_native_short_scope_support_event_v1_admin_operation (
        scope_admin_operation_id
    ),
    ADD CONSTRAINT fk_native_short_scope_support_event_v1_admin_operation
        FOREIGN KEY (
            scope_admin_operation_id,
            venue,
            symbol,
            quote_currency,
            fib_trading_horizon,
            primary_interval,
            supporting_interval
        )
        REFERENCES native_short_scope_admin_operation_v1 (
            scope_admin_operation_id,
            venue,
            symbol,
            quote_currency,
            fib_trading_horizon,
            primary_interval,
            supporting_interval
        ),
    ADD CONSTRAINT chk_native_short_scope_support_event_v1_admin_shape
        CHECK (
            (
                scope_admin_operation_id IS NULL
                AND support_generation IS NULL
            )
            OR (
                scope_admin_operation_id IS NOT NULL
                AND support_generation IS NOT NULL
                AND support_generation > 0
            )
        );


ALTER TABLE native_short_scope_cadence_config_v1
    DROP INDEX uq_native_short_scope_cadence_config_v1_scope_version,
    ADD COLUMN activation_operation_id BIGINT UNSIGNED NULL AFTER is_active,
    ADD COLUMN deactivation_operation_id BIGINT UNSIGNED NULL AFTER activation_operation_id,
    ADD COLUMN support_generation BIGINT UNSIGNED NULL AFTER deactivation_operation_id,
    ADD COLUMN active_slot TINYINT
        GENERATED ALWAYS AS (
            CASE WHEN is_active = 1 THEN 1 ELSE NULL END
        ) STORED AFTER support_generation,
    ADD UNIQUE KEY uq_native_short_scope_cadence_config_v1_active_slot (
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        active_slot
    ),
    ADD UNIQUE KEY uq_native_short_scope_cadence_config_v1_activation_operation (
        activation_operation_id
    ),
    ADD UNIQUE KEY uq_native_short_scope_cadence_config_v1_deactivation_operation (
        deactivation_operation_id
    ),
    ADD CONSTRAINT fk_native_short_scope_cadence_config_v1_activation_operation
        FOREIGN KEY (
            activation_operation_id,
            venue,
            symbol,
            quote_currency,
            fib_trading_horizon,
            primary_interval,
            supporting_interval
        )
        REFERENCES native_short_scope_admin_operation_v1 (
            scope_admin_operation_id,
            venue,
            symbol,
            quote_currency,
            fib_trading_horizon,
            primary_interval,
            supporting_interval
        ),
    ADD CONSTRAINT fk_native_short_scope_cadence_config_v1_deactivation_operation
        FOREIGN KEY (
            deactivation_operation_id,
            venue,
            symbol,
            quote_currency,
            fib_trading_horizon,
            primary_interval,
            supporting_interval
        )
        REFERENCES native_short_scope_admin_operation_v1 (
            scope_admin_operation_id,
            venue,
            symbol,
            quote_currency,
            fib_trading_horizon,
            primary_interval,
            supporting_interval
        ),
    ADD CONSTRAINT chk_native_short_scope_cadence_config_v1_active_effective
        CHECK (is_active <> 1 OR effective_to_utc IS NULL),
    ADD CONSTRAINT chk_native_short_scope_cadence_config_v1_support_generation
        CHECK (support_generation IS NULL OR support_generation > 0),
    ADD CONSTRAINT chk_native_short_scope_cadence_config_v1_activation_shape
        CHECK (
            (activation_operation_id IS NULL AND support_generation IS NULL)
            OR (activation_operation_id IS NOT NULL AND support_generation IS NOT NULL)
        ),
    ADD CONSTRAINT chk_native_short_scope_cadence_config_v1_deactivation_shape
        CHECK (
            deactivation_operation_id IS NULL
            OR (
                activation_operation_id IS NOT NULL
                AND is_active = 0
                AND effective_to_utc IS NOT NULL
            )
        ),
    ADD CONSTRAINT chk_native_short_scope_cadence_config_v1_managed_state
        CHECK (
            activation_operation_id IS NULL
            OR (
                (
                    is_active = 1
                    AND deactivation_operation_id IS NULL
                    AND effective_to_utc IS NULL
                )
                OR (
                    is_active = 0
                    AND deactivation_operation_id IS NOT NULL
                    AND effective_to_utc IS NOT NULL
                )
            )
        );

-- Permanent scope+profile+generation uniqueness on a NULL-safe slot. This
-- replaces the dropped uq_native_short_scope_cadence_config_v1_scope_version
-- guard. effective_generation_slot is a stored generated projection of
-- support_generation onto the reserved legacy sentinel 0 when NULL; because
-- managed support generations are always > 0 they can never collide with the
-- legacy slot. The UNIQUE key therefore:
--   * forbids a second legacy/unmanaged row (slot 0) for one exact scope and
--     cadence profile (restores the invariant the dropped index enforced);
--   * still permits distinct positive managed generations of the same profile;
--   * still rejects a duplicate managed generation of the same profile.
-- Kept in a separate ALTER so the generated column references support_generation
-- only after it is persisted by the ALTER above.
ALTER TABLE native_short_scope_cadence_config_v1
    ADD COLUMN effective_generation_slot BIGINT UNSIGNED
        GENERATED ALWAYS AS (COALESCE(support_generation, 0)) STORED
        AFTER active_slot,
    ADD UNIQUE KEY uq_native_short_scope_cadence_config_v1_profile_generation (
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        cadence_contract_version,
        effective_generation_slot
    );

-- Duplicate attributable support generations are impossible on first
-- application because both attribution columns were absent and are added NULL.
-- The support-event unique key above enforces the preflight invariant from the
-- first attributable event forward without assigning values to legacy rows.
-- The cadence profile-generation unique key uses effective_generation_slot so
-- the same NULL-safe protection covers legacy (slot 0) cadence rows too.
-- Ongoing historical effective-window non-overlap enforcement is intentionally
-- NOT added here: it remains a migration-preflight check plus a future
-- locked repository-transaction validation (the deferred adoption/promotion/
-- removal transaction PR), not a trigger in this pure schema-contract migration.
