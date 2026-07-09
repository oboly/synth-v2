-- Migration: native_short_cadence_v1_seed
-- Boundary: market-only persistent contract only
-- Follows: 20260707_native_short_cadence_unavailable_v1.sql
-- Purpose:
--   Seed the first canonical native SHORT cadence/grace configuration
--   profile (cadence_contract_version = native_short_cadence_v1) into
--   native_short_scope_cadence_config_v1, using exact full canonical scope
--   keys only (no wildcard/default inheritance), for every scope currently
--   SUPPORTED at fib_trading_horizon=SHORT.
--
--   Values are explicit config-owner-authorized native SHORT V1 defaults,
--   recorded in the "Canonical Native SHORT V1 Cadence Profile" section of
--   docs/architecture/native_short_scope_status_contract_v1.md:
--     target_evaluation_interval                = 1h
--     primary_source_freshness_limit_seconds    = 43200 (12h)
--     supporting_source_freshness_limit_seconds = 10800 (3h)
--     evaluation_grace_seconds                  = 900   (15m)
--     recent_scope_grace_seconds                = 3600  (1h)
--
-- Non-goals:
--   - no materializer runner integration
--   - no projection rebuild logic
--   - no health-report switch
--   - no deployment wiring
--   - no wildcard/default inheritance
--   - no changes to native_short_scope_observation_v1, native_short_scope_status_v1,
--     native_short_scope_support_event_v1, native_short_map_v1,
--     native_short_map_generation_event_v1, native_short_map_lifecycle_event_v1,
--     native_short_materializer_run_v1, or native_short_map_scope_v1 schema
--   - no trading or presentation-layer changes

SET @native_short_cadence_v1_effective_from_utc = TIMESTAMP('2026-07-09 00:00:00.000000');

INSERT INTO native_short_scope_cadence_config_v1 (
    venue,
    symbol,
    quote_currency,
    fib_trading_horizon,
    primary_interval,
    supporting_interval,
    cadence_contract_version,
    target_evaluation_interval,
    primary_source_freshness_limit_seconds,
    supporting_source_freshness_limit_seconds,
    evaluation_grace_seconds,
    recent_scope_grace_seconds,
    effective_from_utc,
    effective_to_utc,
    is_active
)
SELECT
    s.venue,
    s.symbol,
    s.quote_currency,
    s.fib_trading_horizon,
    s.primary_interval,
    s.supporting_interval,
    'native_short_cadence_v1',
    '1h',
    43200,
    10800,
    900,
    3600,
    @native_short_cadence_v1_effective_from_utc,
    NULL,
    1
FROM native_short_map_scope_v1 s
WHERE s.fib_trading_horizon = 'SHORT'
  AND s.scope_support_state = 'SUPPORTED'
  AND NOT EXISTS (
      SELECT 1
      FROM native_short_scope_cadence_config_v1 existing
      WHERE existing.venue               = s.venue
        AND existing.symbol              = s.symbol
        AND existing.quote_currency      = s.quote_currency
        AND existing.fib_trading_horizon = s.fib_trading_horizon
        AND existing.primary_interval    = s.primary_interval
        AND existing.supporting_interval = s.supporting_interval
        AND existing.cadence_contract_version = 'native_short_cadence_v1'
  );
