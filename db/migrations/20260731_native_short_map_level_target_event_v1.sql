-- Migration: native_short_map_level_target_event_v1
-- Boundary: market-only · account-agnostic · append-only prospective event ledger
-- Authorization: Synth Outcome & Reliability Program (prospective outcome
--   evidence). NOT authorized as evidence of, or a response to, any canonical
--   BTC/IOST lifecycle regression -- see docs/todo/
--   profit_plan_target_lifecycle_history_truth_v1.md and
--   docs/todo/native_short_map_level_status_v1.md for the retained,
--   unmodified evidence-gate record this authorization sits alongside.
--
-- Purpose:
--   1. Persist an immutable, append-only REACHED/PASSED transition ledger for
--      individual native SHORT canonical V1 SELL target levels, scoped to the
--      exact immutable map identity.
--   2. Preserve event-time (causal closed 4h candle) distinctly from
--      recording-time (writer wall-clock insert time).
--   3. Provide deterministic canonical identity (map_id + level role + side +
--      immutable price + event type) so no free-text/symbol matching can ever
--      select or duplicate a target event.
-- Non-goals:
--   - no historical backfill of pre-coverage maps/targets
--   - no EXPIRED detector
--   - no PostTargetReentryProjection
--   - no runner/scheduler/timer change
--   - no reporting/UI/account/broker/decision/execution/executor change

CREATE TABLE IF NOT EXISTS native_short_map_level_target_event_v1 (
    target_event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL,
    fib_trading_horizon VARCHAR(32) NOT NULL,
    primary_interval    VARCHAR(16) NOT NULL,
    supporting_interval VARCHAR(16) NOT NULL,

    map_id       BIGINT UNSIGNED NOT NULL COMMENT 'Exact immutable map identity; never carried across rollover.',
    map_cycle_id VARCHAR(255) NOT NULL COMMENT 'Copied from native_short_map_v1 for redundant verification only.',

    canonical_map_level_role VARCHAR(32) NOT NULL,
    side                     VARCHAR(8) NOT NULL,
    canonical_unrounded_price DECIMAL(38, 18) NOT NULL COMMENT 'Immutable analytical map geometry price; part of canonical identity.',

    target_event_type VARCHAR(16) NOT NULL COMMENT 'REACHED | PASSED -- no ACTIVE event; ACTIVE is absence of a terminal event.',

    causal_candle_close_ts_utc DATETIME(6) NOT NULL COMMENT 'Closed 4h candle interval-close boundary; the sole event-time source.',
    causal_candle_high_price   DECIMAL(30, 12) NULL COMMENT 'Required evidence for REACHED.',
    causal_candle_close_price  DECIMAL(30, 12) NULL COMMENT 'Required evidence for PASSED.',

    effective_at_utc DATETIME(6) NOT NULL COMMENT 'Must equal causal_candle_close_ts_utc exactly; never processing time.',
    recorded_at_utc  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Writer wall-clock recording time; distinct from effective_at_utc; never updated.',

    evaluation_reference VARCHAR(64) NOT NULL DEFAULT 'PRIMARY_4H_CLOSED_CANDLES',
    reason_code           VARCHAR(96) NOT NULL,

    writer_name            VARCHAR(96) NOT NULL,
    writer_version          VARCHAR(32) NOT NULL,
    writer_invocation_uuid  CHAR(36) NOT NULL COMMENT 'Provenance attribution; see native_short_writer_provenance_v1.',

    same_candle_reached_skipped TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'PASSED rows only: 1 when the same causal candle both reached and closed above the level, so no separate REACHED event exists for this level.',

    event_metadata_json LONGTEXT NULL,

    created_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_native_short_map_level_target_event_v1_identity (
        map_id, canonical_map_level_role, side, canonical_unrounded_price, target_event_type
    ),
    KEY idx_native_short_map_level_target_event_v1_map (map_id),
    KEY idx_native_short_map_level_target_event_v1_scope (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval
    ),
    KEY idx_native_short_map_level_target_event_v1_effective (effective_at_utc),
    KEY idx_native_short_map_level_target_event_v1_recorded (recorded_at_utc),

    CONSTRAINT fk_native_short_map_level_target_event_v1_map
        FOREIGN KEY (map_id) REFERENCES native_short_map_v1 (map_id),

    CONSTRAINT chk_native_short_map_level_target_event_v1_horizon
        CHECK (fib_trading_horizon = 'SHORT'),
    CONSTRAINT chk_native_short_map_level_target_event_v1_primary
        CHECK (primary_interval = '4h'),
    CONSTRAINT chk_native_short_map_level_target_event_v1_supporting
        CHECK (supporting_interval = '1h'),
    CONSTRAINT chk_native_short_map_level_target_event_v1_role
        CHECK (canonical_map_level_role IN ('SELL_EXT_1_272', 'SELL_EXT_1_618', 'SELL_EXT_2_000')),
    CONSTRAINT chk_native_short_map_level_target_event_v1_side
        CHECK (side = 'SELL'),
    CONSTRAINT chk_native_short_map_level_target_event_v1_price_positive
        CHECK (canonical_unrounded_price > 0),
    CONSTRAINT chk_native_short_map_level_target_event_v1_type
        CHECK (target_event_type IN ('REACHED', 'PASSED')),
    CONSTRAINT chk_native_short_map_level_target_event_v1_eval_ref
        CHECK (evaluation_reference = 'PRIMARY_4H_CLOSED_CANDLES'),
    CONSTRAINT chk_native_short_map_level_target_event_v1_reason
        CHECK (reason_code IN (
            'PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE',
            'PRIMARY_CLOSE_PASSED_LEVEL'
        )),
    CONSTRAINT chk_native_short_map_level_target_event_v1_eff_eq_causal
        CHECK (effective_at_utc = causal_candle_close_ts_utc),
    CONSTRAINT chk_native_short_map_level_target_event_v1_reached_evidence
        CHECK (
            (target_event_type = 'REACHED'
                AND causal_candle_high_price IS NOT NULL
                AND reason_code = 'PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE'
                AND same_candle_reached_skipped = 0)
            OR
            (target_event_type = 'PASSED'
                AND causal_candle_close_price IS NOT NULL
                AND reason_code = 'PRIMARY_CLOSE_PASSED_LEVEL')
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only prospective REACHED/PASSED target-event ledger for native SHORT V1 SELL levels. One row per exact map-level identity per event type; never updated after insert.';


CREATE TABLE IF NOT EXISTS native_short_map_level_target_event_coverage_v1 (
    map_id BIGINT UNSIGNED NOT NULL PRIMARY KEY COMMENT 'Exactly one immutable coverage row per exact map identity.',

    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    quote_currency      VARCHAR(16) NOT NULL,
    fib_trading_horizon VARCHAR(32) NOT NULL,
    primary_interval    VARCHAR(16) NOT NULL,
    supporting_interval VARCHAR(16) NOT NULL,

    map_cycle_id VARCHAR(255) NOT NULL,

    publication_boundary_utc                 DATETIME(6) NOT NULL COMMENT 'native_short_map_v1.published_at_utc at establishment time.',
    requested_watermark_utc_at_establishment DATETIME(6) NOT NULL COMMENT 'The caller-supplied watermark in effect the one time this row was established; never re-read afterward.',
    coverage_cutoff_utc                      DATETIME(6) NOT NULL COMMENT 'Immutable per-map causal cutoff = GREATEST(publication_boundary_utc, requested_watermark_utc_at_establishment). Never rewritten by a later run.',

    established_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Writer wall-clock time this coverage row was first inserted; never updated.',

    writer_name            VARCHAR(96) NOT NULL,
    writer_version          VARCHAR(32) NOT NULL,
    writer_invocation_uuid  CHAR(36) NOT NULL,

    KEY idx_native_short_map_level_target_event_coverage_v1_scope (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval
    ),
    KEY idx_native_short_map_level_target_event_coverage_v1_cutoff (coverage_cutoff_utc),

    CONSTRAINT fk_native_short_map_level_target_event_coverage_v1_map
        FOREIGN KEY (map_id) REFERENCES native_short_map_v1 (map_id),

    CONSTRAINT chk_native_short_map_level_target_event_coverage_v1_horizon
        CHECK (fib_trading_horizon = 'SHORT'),
    CONSTRAINT chk_native_short_map_level_target_event_coverage_v1_cutoff_bnd
        CHECK (
            coverage_cutoff_utc >= publication_boundary_utc
            AND coverage_cutoff_utc >= requested_watermark_utc_at_establishment
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Immutable per-map target-event coverage activation boundary. Established at most once per map_id; the persisted coverage_cutoff_utc is the sole durable causal-cutoff authority for that map and is never recomputed by a later watermark.';


CREATE OR REPLACE VIEW native_short_map_level_target_event_current_state_v1 AS
SELECT
    map_id,
    venue,
    symbol,
    quote_currency,
    fib_trading_horizon,
    primary_interval,
    supporting_interval,
    canonical_map_level_role,
    side,
    canonical_unrounded_price,
    CASE
        WHEN SUM(CASE WHEN target_event_type = 'PASSED' THEN 1 ELSE 0 END) > 0 THEN 'PASSED'
        WHEN SUM(CASE WHEN target_event_type = 'REACHED' THEN 1 ELSE 0 END) > 0 THEN 'REACHED'
        ELSE 'ACTIVE'
    END AS target_event_state,
    MIN(CASE WHEN target_event_type = 'REACHED' THEN effective_at_utc END) AS reached_effective_at_utc,
    MIN(CASE WHEN target_event_type = 'PASSED' THEN effective_at_utc END) AS passed_effective_at_utc
FROM native_short_map_level_target_event_v1
GROUP BY
    map_id, venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
    canonical_map_level_role, side, canonical_unrounded_price;
