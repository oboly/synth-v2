-- Migration: native_short_cadence_unavailable_v1
-- Boundary: market-only persistent contract only
-- Follows: 20260706_native_short_scope_status_persistence_v1.sql (PR A1)
-- Purpose (PR A1b, Amendment 1 to
--   docs/architecture/native_short_scope_status_contract_v1.md):
--   1. Represent the "no eligible cadence config at as_of_utc" configuration
--      state on native_short_scope_observation_v1 and native_short_scope_status_v1
--      without inventing sentinel cadence versions or fabricated freshness
--      limits, and without misclassifying it as a source/candle failure.
--   2. Add SKIPPED_CONFIGURATION_UNAVAILABLE to the observation_status domain,
--      relax the columns that cannot be known when evaluation never started,
--      and enforce conditional nullability with named CHECK constraints.
--   3. Add CONFIGURATION_UNAVAILABLE to the scope_status_code domain (new
--      highest precedence), BLOCKED_CONFIGURATION to actionability_state, and
--      OBSERVATION_CONFIGURATION_UNAVAILABLE to observation_freshness_state,
--      relax the columns that cannot be known without a configured cadence
--      version, and enforce conditional nullability with named CHECK
--      constraints.
-- Non-goals:
--   - no materializer runner integration
--   - no projection rebuild logic
--   - no health-report switch
--   - no deployment wiring
--   - no seed cadence config rows
--   - no changes to native_short_scope_support_event_v1, native_short_map_v1,
--     native_short_map_generation_event_v1, native_short_map_lifecycle_event_v1,
--     native_short_materializer_run_v1, or native_short_map_scope_v1
--   - no trading or presentation-layer changes
--   - no mutation of existing historical rows

-- ---------------------------------------------------------------------------
-- native_short_scope_observation_v1: relax columns for
-- SKIPPED_CONFIGURATION_UNAVAILABLE only.
-- ---------------------------------------------------------------------------

ALTER TABLE native_short_scope_observation_v1
    MODIFY COLUMN cadence_contract_version VARCHAR(32) NULL,
    MODIFY COLUMN source_state VARCHAR(64) NULL COMMENT 'SOURCE_CURRENT | SOURCE_STALE | SOURCE_UNAVAILABLE; NULL only when observation_status=SKIPPED_CONFIGURATION_UNAVAILABLE',
    MODIFY COLUMN primary_source_freshness_limit_seconds INT UNSIGNED NULL,
    MODIFY COLUMN supporting_source_freshness_limit_seconds INT UNSIGNED NULL,
    MODIFY COLUMN geometry_action VARCHAR(64) NULL COMMENT 'PUBLISHED_NEW_MAP | UNCHANGED_GEOMETRY | REJECTED_CONTEXT | NO_MAP_AVAILABLE; NULL only when observation_status=SKIPPED_CONFIGURATION_UNAVAILABLE',
    MODIFY COLUMN observation_status VARCHAR(64) NOT NULL COMMENT 'EVALUATED | FAILED | SKIPPED_SOURCE_UNAVAILABLE | SKIPPED_CONFIGURATION_UNAVAILABLE';

ALTER TABLE native_short_scope_observation_v1
    DROP CONSTRAINT chk_native_short_scope_observation_v1_status,
    DROP CONSTRAINT chk_native_short_scope_observation_v1_source,
    DROP CONSTRAINT chk_native_short_scope_observation_v1_geometry;

ALTER TABLE native_short_scope_observation_v1
    ADD CONSTRAINT chk_native_short_scope_observation_v1_status
        CHECK (observation_status IN (
            'EVALUATED',
            'FAILED',
            'SKIPPED_SOURCE_UNAVAILABLE',
            'SKIPPED_CONFIGURATION_UNAVAILABLE'
        )),
    ADD CONSTRAINT chk_native_short_scope_observation_v1_source
        CHECK (
            (observation_status = 'SKIPPED_CONFIGURATION_UNAVAILABLE' AND source_state IS NULL)
            OR
            (observation_status <> 'SKIPPED_CONFIGURATION_UNAVAILABLE' AND source_state IS NOT NULL AND source_state IN ('SOURCE_CURRENT', 'SOURCE_STALE', 'SOURCE_UNAVAILABLE'))
        ),
    ADD CONSTRAINT chk_native_short_scope_observation_v1_geometry
        CHECK (
            (observation_status = 'SKIPPED_CONFIGURATION_UNAVAILABLE' AND geometry_action IS NULL)
            OR
            (observation_status <> 'SKIPPED_CONFIGURATION_UNAVAILABLE' AND geometry_action IS NOT NULL AND geometry_action IN ('PUBLISHED_NEW_MAP', 'UNCHANGED_GEOMETRY', 'REJECTED_CONTEXT', 'NO_MAP_AVAILABLE'))
        ),
    ADD CONSTRAINT chk_native_short_scope_observation_v1_cadence_version
        CHECK (
            (observation_status = 'SKIPPED_CONFIGURATION_UNAVAILABLE' AND cadence_contract_version IS NULL)
            OR
            (observation_status <> 'SKIPPED_CONFIGURATION_UNAVAILABLE' AND cadence_contract_version IS NOT NULL)
        ),
    ADD CONSTRAINT chk_native_short_scope_observation_v1_freshness_limits
        CHECK (
            (
                observation_status = 'SKIPPED_CONFIGURATION_UNAVAILABLE'
                AND primary_source_freshness_limit_seconds IS NULL
                AND supporting_source_freshness_limit_seconds IS NULL
            )
            OR
            (
                observation_status <> 'SKIPPED_CONFIGURATION_UNAVAILABLE'
                AND primary_source_freshness_limit_seconds IS NOT NULL
                AND supporting_source_freshness_limit_seconds IS NOT NULL
            )
        ),
    ADD CONSTRAINT chk_native_short_scope_observation_v1_config_reason
        CHECK (
            observation_status <> 'SKIPPED_CONFIGURATION_UNAVAILABLE'
            OR (observation_reason_code IS NOT NULL AND observation_reason_code = 'NO_ELIGIBLE_CADENCE_CONFIG')
        ),
    ADD CONSTRAINT chk_native_short_scope_observation_v1_config_due
        CHECK (
            observation_status <> 'SKIPPED_CONFIGURATION_UNAVAILABLE'
            OR evaluation_due_at_utc IS NULL
        );

-- ---------------------------------------------------------------------------
-- native_short_scope_status_v1: relax columns for CONFIGURATION_UNAVAILABLE
-- only.
-- ---------------------------------------------------------------------------

ALTER TABLE native_short_scope_status_v1
    MODIFY COLUMN scope_status_code VARCHAR(64) NOT NULL COMMENT 'CONFIGURATION_UNAVAILABLE | SOURCE_UNAVAILABLE | SOURCE_STALE | MAP_INVALIDATED | MAP_COMPLETED | SCOPE_RECENTLY_ADDED | OBSERVATION_OVERDUE | CURRENT_EVALUATION',
    MODIFY COLUMN observation_freshness_state VARCHAR(64) NOT NULL COMMENT 'OBSERVATION_CURRENT | OBSERVATION_OVERDUE | NO_OBSERVATION | OBSERVATION_CONFIGURATION_UNAVAILABLE',
    MODIFY COLUMN source_freshness_state VARCHAR(64) NULL COMMENT 'SOURCE_CURRENT | SOURCE_STALE | SOURCE_UNAVAILABLE; NULL only when scope_status_code=CONFIGURATION_UNAVAILABLE',
    MODIFY COLUMN actionability_state VARCHAR(64) NOT NULL COMMENT 'BLOCKED_CONFIGURATION | ACTIONABLE_ACTIVE_MAP | NO_ACTIONABLE_MAP | TERMINAL_MAP | BLOCKED_SOURCE | BLOCKED_OBSERVATION | BLOCKED_SCOPE',
    MODIFY COLUMN primary_source_freshness_limit_seconds INT UNSIGNED NULL,
    MODIFY COLUMN supporting_source_freshness_limit_seconds INT UNSIGNED NULL,
    MODIFY COLUMN cadence_contract_version VARCHAR(32) NULL;

ALTER TABLE native_short_scope_status_v1
    DROP CONSTRAINT chk_native_short_scope_status_v1_code,
    DROP CONSTRAINT chk_native_short_scope_status_v1_observation_freshness,
    DROP CONSTRAINT chk_native_short_scope_status_v1_source_freshness,
    DROP CONSTRAINT chk_native_short_scope_status_v1_actionability;

ALTER TABLE native_short_scope_status_v1
    ADD CONSTRAINT chk_native_short_scope_status_v1_code
        CHECK (scope_status_code IN (
            'CONFIGURATION_UNAVAILABLE',
            'SOURCE_UNAVAILABLE',
            'SOURCE_STALE',
            'MAP_INVALIDATED',
            'MAP_COMPLETED',
            'SCOPE_RECENTLY_ADDED',
            'OBSERVATION_OVERDUE',
            'CURRENT_EVALUATION'
        )),
    ADD CONSTRAINT chk_native_short_scope_status_v1_observation_freshness
        CHECK (observation_freshness_state IN (
            'OBSERVATION_CURRENT',
            'OBSERVATION_OVERDUE',
            'NO_OBSERVATION',
            'OBSERVATION_CONFIGURATION_UNAVAILABLE'
        )),
    ADD CONSTRAINT chk_native_short_scope_status_v1_source_freshness
        CHECK (
            (scope_status_code = 'CONFIGURATION_UNAVAILABLE' AND source_freshness_state IS NULL)
            OR
            (scope_status_code <> 'CONFIGURATION_UNAVAILABLE' AND source_freshness_state IS NOT NULL AND source_freshness_state IN ('SOURCE_CURRENT', 'SOURCE_STALE', 'SOURCE_UNAVAILABLE'))
        ),
    ADD CONSTRAINT chk_native_short_scope_status_v1_actionability
        CHECK (actionability_state IN (
            'BLOCKED_CONFIGURATION',
            'ACTIONABLE_ACTIVE_MAP',
            'NO_ACTIONABLE_MAP',
            'TERMINAL_MAP',
            'BLOCKED_SOURCE',
            'BLOCKED_OBSERVATION',
            'BLOCKED_SCOPE'
        )),
    ADD CONSTRAINT chk_native_short_scope_status_v1_config_cadence_version
        CHECK (
            (scope_status_code = 'CONFIGURATION_UNAVAILABLE' AND cadence_contract_version IS NULL)
            OR
            (scope_status_code <> 'CONFIGURATION_UNAVAILABLE' AND cadence_contract_version IS NOT NULL)
        ),
    ADD CONSTRAINT chk_native_short_scope_status_v1_config_freshness_limits
        CHECK (
            (
                scope_status_code = 'CONFIGURATION_UNAVAILABLE'
                AND primary_source_freshness_limit_seconds IS NULL
                AND supporting_source_freshness_limit_seconds IS NULL
            )
            OR
            (
                scope_status_code <> 'CONFIGURATION_UNAVAILABLE'
                AND primary_source_freshness_limit_seconds IS NOT NULL
                AND supporting_source_freshness_limit_seconds IS NOT NULL
            )
        ),
    ADD CONSTRAINT chk_native_short_scope_status_v1_config_reason
        CHECK (
            scope_status_code <> 'CONFIGURATION_UNAVAILABLE'
            OR (scope_status_reason_code IS NOT NULL AND scope_status_reason_code = 'NO_ELIGIBLE_CADENCE_CONFIG')
        ),
    ADD CONSTRAINT chk_native_short_scope_status_v1_config_actionability
        CHECK (
            scope_status_code <> 'CONFIGURATION_UNAVAILABLE'
            OR actionability_state = 'BLOCKED_CONFIGURATION'
        ),
    ADD CONSTRAINT chk_native_short_scope_status_v1_config_obs_freshness
        CHECK (
            scope_status_code <> 'CONFIGURATION_UNAVAILABLE'
            OR observation_freshness_state = 'OBSERVATION_CONFIGURATION_UNAVAILABLE'
        ),
    ADD CONSTRAINT chk_native_short_scope_status_v1_config_next_eval
        CHECK (
            scope_status_code <> 'CONFIGURATION_UNAVAILABLE'
            OR next_expected_evaluation_at_utc IS NULL
        ),
    ADD CONSTRAINT chk_native_short_scope_status_v1_config_overdue_after
        CHECK (
            scope_status_code <> 'CONFIGURATION_UNAVAILABLE'
            OR observation_overdue_after_utc IS NULL
        );
