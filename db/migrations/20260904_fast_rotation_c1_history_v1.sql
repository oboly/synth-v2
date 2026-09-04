-- Migration: fast_rotation_c1_history_v1
-- Issue: #733
-- Boundary: market-only · account-agnostic · persistence only
-- No selection, decision permission, execution planning, broker calls, or orders.
--
-- Purpose:
--   Persist the validated #593 C1 raw Rotation observation as replayable,
--   versioned canonical market evidence without changing the frozen C1
--   formula/sign semantics and without reusing the broad/regime Rotation V1
--   tables for a different model family/horizon.

CREATE TABLE IF NOT EXISTS fast_rotation_c1_observation_v1 (
    c1_observation_id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    venue                              VARCHAR(32)  NOT NULL,
    asset_id                           INT          NOT NULL,
    market                             VARCHAR(32)  NOT NULL,
    asof_ts_utc                        DATETIME(6)  NOT NULL,

    candidate_id                       VARCHAR(8)   NOT NULL,
    rotation_model                     VARCHAR(96)  NOT NULL,
    rotation_model_version             VARCHAR(32)  NOT NULL,
    input_interval                     VARCHAR(8)   NOT NULL,
    lookback_horizon                   VARCHAR(160) NOT NULL,
    effective_horizon                  VARCHAR(32)  NOT NULL,
    observed_lifecycle                 VARCHAR(32)  NOT NULL,

    rotation_score                     DECIMAL(18, 6) NULL,
    relative_return_unit               DECIMAL(28, 12) NULL,
    signed_flow_unit                   DECIMAL(28, 12) NULL,
    relative_acceleration_unit         DECIMAL(28, 12) NULL,
    cohort_size                        SMALLINT UNSIGNED NOT NULL,

    freshness_state                    VARCHAR(32)  NOT NULL,
    data_quality                       VARCHAR(32)  NOT NULL,
    reason_code                        VARCHAR(96)  NOT NULL,

    source_provenance                  VARCHAR(512) NOT NULL,
    frozen_replay_source_sha256        CHAR(64)     NOT NULL,
    frozen_final_holdout_fingerprint   CHAR(64)     NOT NULL,

    created_at                         DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (c1_observation_id),

    UNIQUE KEY uq_fast_rotation_c1_identity (
        venue,
        market,
        rotation_model,
        rotation_model_version,
        effective_horizon,
        asof_ts_utc
    ),

    KEY idx_fast_rotation_c1_asset_asof (asset_id, asof_ts_utc),
    KEY idx_fast_rotation_c1_market_asof (market, asof_ts_utc),
    KEY idx_fast_rotation_c1_quality_asof (data_quality, asof_ts_utc),

    CONSTRAINT chk_fast_rotation_c1_candidate
        CHECK (candidate_id = 'C1'),
    CONSTRAINT chk_fast_rotation_c1_input_interval
        CHECK (input_interval = '15m'),
    CONSTRAINT chk_fast_rotation_c1_effective_horizon
        CHECK (effective_horizon = 'VERY_SHORT'),
    CONSTRAINT chk_fast_rotation_c1_lifecycle
        CHECK (observed_lifecycle = 'UNMEASURED'),
    CONSTRAINT chk_fast_rotation_c1_freshness
        CHECK (freshness_state IN ('FRESH', 'STALE', 'INSUFFICIENT_DATA', 'UNKNOWN')),
    CONSTRAINT chk_fast_rotation_c1_quality
        CHECK (data_quality IN ('COMPLETE', 'INSUFFICIENT_DATA')),
    CONSTRAINT chk_fast_rotation_c1_score
        CHECK (rotation_score IS NULL OR rotation_score BETWEEN -100 AND 100)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Validated #593 C1 fast Rotation raw evidence history. Market-only, append/idempotent, no trading authority.';
