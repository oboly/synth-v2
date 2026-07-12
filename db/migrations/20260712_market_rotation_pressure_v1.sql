-- Migration: market_rotation_pressure_v1
-- Boundary: research-only · market-only · account-agnostic
--           no account, balance, position, order, broker, decision, planning, or execution coupling
--
-- Purpose:
--   Persist deterministic Synth-native 24h/7d rotation-pressure scores derived from
--   market_rotation_history_v1 observations. These are inferred directional pressure
--   measurements, not verified capital-flow or fund-flow records.
--
-- Safety markers:
--   broker_private_calls=0  broker_writes=0  order_submission=0  live_orders=0
--   selection_engine=none  decision_gate=none  execution_planner=none  executor=none

CREATE TABLE IF NOT EXISTS market_rotation_pressure_snapshot_v1 (
    pressure_snapshot_id          BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
    as_of_ts_utc                  DATETIME(6)       NOT NULL,
    venue                         VARCHAR(32)       NOT NULL DEFAULT 'bitvavo',
    model_version                 VARCHAR(16)       NOT NULL,

    eligible_asset_count          SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    excluded_missing_pair_count   SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    positive_count                SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    neutral_count                 SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    negative_count                SMALLINT UNSIGNED NOT NULL DEFAULT 0,

    market_score                  DECIMAL(8, 4)     NOT NULL,
    positive_breadth_ratio        DECIMAL(7, 6)     NOT NULL,
    negative_breadth_ratio        DECIMAL(7, 6)     NOT NULL,

    acceleration_state            VARCHAR(32)       NOT NULL,
    concentration_state           VARCHAR(32)       NOT NULL,
    confirmation_state            VARCHAR(32)       NOT NULL,
    market_direction              VARCHAR(32)       NOT NULL,
    evidence_light_count          TINYINT UNSIGNED  NOT NULL DEFAULT 0,

    created_at                     DATETIME(6)       NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (pressure_snapshot_id),
    UNIQUE KEY uq_mrp_snapshot (as_of_ts_utc, venue, model_version),
    KEY idx_mrp_snapshot_latest (venue, model_version, as_of_ts_utc),

    CONSTRAINT chk_mrp_market_score
        CHECK (market_score BETWEEN -100 AND 100),
    CONSTRAINT chk_mrp_positive_breadth
        CHECK (positive_breadth_ratio BETWEEN 0 AND 1),
    CONSTRAINT chk_mrp_negative_breadth
        CHECK (negative_breadth_ratio BETWEEN 0 AND 1),
    CONSTRAINT chk_mrp_light_count
        CHECK (evidence_light_count BETWEEN 0 AND 5),
    CONSTRAINT chk_mrp_direction
        CHECK (market_direction IN ('ROTATION_IN', 'ROTATION_OUT', 'MIXED')),
    CONSTRAINT chk_mrp_acceleration
        CHECK (acceleration_state IN ('ACCELERATING_IN', 'ACCELERATING_OUT', 'STABLE', 'UNKNOWN')),
    CONSTRAINT chk_mrp_concentration
        CHECK (concentration_state IN ('BROAD', 'SELECTIVE', 'CONCENTRATED', 'MIXED', 'UNKNOWN')),
    CONSTRAINT chk_mrp_confirmation
        CHECK (confirmation_state IN ('CONFIRMED', 'PARTIAL', 'CONFLICTING', 'MIXED'))

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Market-only aggregate rotation-pressure state derived from 24h/7d rotation observations.';


CREATE TABLE IF NOT EXISTS market_rotation_pressure_observation_v1 (
    pressure_obs_id               BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
    pressure_snapshot_id          BIGINT UNSIGNED   NOT NULL,

    asset_id                      INT               NOT NULL,
    market                        VARCHAR(32)       NOT NULL,
    source_snapshot_24h_id        BIGINT UNSIGNED   NOT NULL,
    source_snapshot_7d_id         BIGINT UNSIGNED   NOT NULL,
    as_of_ts_utc                  DATETIME(6)       NOT NULL,
    model_version                 VARCHAR(16)       NOT NULL,

    raw_return_24h_pct            DECIMAL(18, 6)    NOT NULL,
    raw_relative_volume_24h       DECIMAL(18, 6)    NOT NULL,
    raw_return_7d_pct             DECIMAL(18, 6)    NOT NULL,
    raw_relative_volume_7d        DECIMAL(18, 6)    NOT NULL,
    raw_acceleration_pct          DECIMAL(18, 6)    NOT NULL,
    raw_market_relative_pct       DECIMAL(18, 6)    NOT NULL,

    score_return_24h              DECIMAL(8, 4)     NOT NULL,
    score_signed_volume_24h       DECIMAL(8, 4)     NOT NULL,
    score_return_7d               DECIMAL(8, 4)     NOT NULL,
    score_signed_volume_7d        DECIMAL(8, 4)     NOT NULL,
    score_acceleration            DECIMAL(8, 4)     NOT NULL,
    score_market_relative         DECIMAL(8, 4)     NOT NULL,
    score_persistence             DECIMAL(8, 4)     NOT NULL,
    score_total                   DECIMAL(8, 4)     NOT NULL,

    pressure_state                VARCHAR(32)       NOT NULL,
    phase_state                   VARCHAR(32)       NOT NULL,

    created_at                    DATETIME(6)       NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (pressure_obs_id),
    UNIQUE KEY uq_mrp_observation (pressure_snapshot_id, asset_id),
    KEY idx_mrp_obs_latest (asset_id, as_of_ts_utc),
    KEY idx_mrp_obs_market_score (as_of_ts_utc, score_total),
    KEY idx_mrp_obs_state (pressure_state, as_of_ts_utc),

    CONSTRAINT chk_mrp_obs_score_total
        CHECK (score_total BETWEEN -100 AND 100),
    CONSTRAINT chk_mrp_obs_pressure_state
        CHECK (pressure_state IN (
            'STRONG_ROTATION_IN',
            'ROTATION_IN',
            'NEUTRAL_OR_MIXED',
            'ROTATION_OUT',
            'STRONG_ROTATION_OUT'
        )),
    CONSTRAINT chk_mrp_obs_phase_state
        CHECK (phase_state IN (
            'EARLY_REVERSAL_IN',
            'ACCELERATING_IN',
            'SUSTAINED_IN',
            'ROTATION_IN',
            'DISTRIBUTION_RISK',
            'COOLING_IN_UPTREND',
            'ACCELERATING_OUT',
            'SUSTAINED_OUT',
            'ROTATION_OUT',
            'BOUNCE_IN_DOWNTREND',
            'MIXED'
        ))

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Per-asset Synth rotation-pressure scores. Append-only and account-agnostic.';
