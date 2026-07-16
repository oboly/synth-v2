-- Migration: Sector Rotation Engine v1
-- Boundary: research/analytics only; market-only; account-agnostic.
-- Source truth: active point-in-time asset_cluster_membership rows and canonical
-- obs_market_candle observations. asset.sector is not a scoring input.
-- Price and quote-volume behavior is proxy rotation, never measured capital flow.
--
-- Safety markers:
-- broker_private_calls=0  broker_writes=0  order_submission=0  live_orders=0
-- selection_engine=none  decision_gate=none  execution_planner=none  executor=none

CREATE TABLE IF NOT EXISTS sector_rotation_snapshot (
    sector_rotation_snapshot_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    sector_code                       VARCHAR(64)     NOT NULL,
    venue                             VARCHAR(32)     NOT NULL,
    source_interval_code              VARCHAR(16)     NOT NULL DEFAULT '1h',
    window_code                       VARCHAR(8)      NOT NULL,
    asof_ts_utc                       DATETIME(6)     NOT NULL,

    weighted_return                   DECIMAL(18,8)   NULL,
    median_return                     DECIMAL(18,8)   NULL,
    positive_participation_pct        DECIMAL(11,8)   NULL,
    negative_participation_pct        DECIMAL(11,8)   NULL,
    benchmark_outperformance_pct      DECIMAL(11,8)   NULL,
    relative_strength_vs_btc          DECIMAL(18,8)   NULL,
    relative_strength_vs_eth          DECIMAL(18,8)   NULL,
    sector_volume_share               DECIMAL(11,8)   NULL,
    sector_volume_share_change        DECIMAL(12,8)   NULL,
    momentum_positive_pct             DECIMAL(11,8)   NULL,
    dispersion                        DECIMAL(18,8)   NULL,

    member_count                      SMALLINT UNSIGNED NOT NULL,
    eligible_member_count             SMALLINT UNSIGNED NOT NULL,
    effective_weighted_member_count   DECIMAL(12,8)   NOT NULL,
    participation_ratio               DECIMAL(11,8)   NOT NULL,
    coverage_ratio                    DECIMAL(11,8)   NOT NULL,
    liquidity_quality                 DECIMAL(11,8)   NULL,
    dominant_member_weight_pct        DECIMAL(11,8)   NULL,

    persistence_score                 DECIMAL(8,4)    NOT NULL,
    persistence_history_count         TINYINT UNSIGNED NOT NULL,
    persistence_status                VARCHAR(32)     NOT NULL,
    rotation_score                    DECIMAL(8,4)    NOT NULL,
    rotation_state                    VARCHAR(40)     NOT NULL,
    confidence                        DECIMAL(11,8)   NOT NULL,

    component_json                    JSON            NOT NULL,
    supporting_flags_json             JSON            NOT NULL,
    taxonomy_versions_json            JSON            NOT NULL,
    input_hash                        CHAR(64)        NOT NULL,
    model_version                     VARCHAR(64)     NOT NULL,
    generated_ts_utc                  DATETIME(6)     NOT NULL,
    created_ts_utc                    DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc                    DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                                       ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (sector_rotation_snapshot_id),
    UNIQUE KEY uq_sector_rotation_snapshot (
        sector_code, venue, window_code, asof_ts_utc, model_version
    ),
    KEY ix_sector_rotation_latest (
        venue, window_code, model_version, asof_ts_utc
    ),
    KEY ix_sector_rotation_state (
        rotation_state, window_code, asof_ts_utc
    ),
    KEY ix_sector_rotation_input_hash (input_hash),

    CONSTRAINT fk_sector_rotation_definition
        FOREIGN KEY (sector_code) REFERENCES sector_definition (sector_code),
    CONSTRAINT chk_sector_rotation_window
        CHECK (window_code IN ('1h', '4h', '1d', '7d')),
    CONSTRAINT chk_sector_rotation_member_counts
        CHECK (eligible_member_count <= member_count),
    CONSTRAINT chk_sector_rotation_effective_members
        CHECK (effective_weighted_member_count >= 0),
    CONSTRAINT chk_sector_rotation_participation_ratio
        CHECK (participation_ratio BETWEEN 0 AND 1),
    CONSTRAINT chk_sector_rotation_coverage_ratio
        CHECK (coverage_ratio BETWEEN 0 AND 1),
    CONSTRAINT chk_sector_rotation_confidence
        CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT chk_sector_rotation_score
        CHECK (rotation_score BETWEEN -100 AND 100),
    CONSTRAINT chk_sector_rotation_persistence_score
        CHECK (persistence_score BETWEEN -100 AND 100),
    CONSTRAINT chk_sector_rotation_positive_participation
        CHECK (positive_participation_pct IS NULL OR positive_participation_pct BETWEEN 0 AND 100),
    CONSTRAINT chk_sector_rotation_negative_participation
        CHECK (negative_participation_pct IS NULL OR negative_participation_pct BETWEEN 0 AND 100),
    CONSTRAINT chk_sector_rotation_benchmark_outperformance
        CHECK (benchmark_outperformance_pct IS NULL OR benchmark_outperformance_pct BETWEEN 0 AND 100),
    CONSTRAINT chk_sector_rotation_volume_share
        CHECK (sector_volume_share IS NULL OR sector_volume_share BETWEEN 0 AND 100),
    CONSTRAINT chk_sector_rotation_momentum_positive
        CHECK (momentum_positive_pct IS NULL OR momentum_positive_pct BETWEEN 0 AND 100),
    CONSTRAINT chk_sector_rotation_liquidity_quality
        CHECK (liquidity_quality IS NULL OR liquidity_quality BETWEEN 0 AND 100),
    CONSTRAINT chk_sector_rotation_dominant_member
        CHECK (dominant_member_weight_pct IS NULL OR dominant_member_weight_pct BETWEEN 0 AND 100),
    CONSTRAINT chk_sector_rotation_persistence_status
        CHECK (persistence_status IN ('INSUFFICIENT_HISTORY', 'PARTIAL_HISTORY', 'AVAILABLE')),
    CONSTRAINT chk_sector_rotation_state
        CHECK (rotation_state IN (
            'LEADING',
            'IMPROVING',
            'NEUTRAL',
            'WEAKENING',
            'LAGGING',
            'ROTATION_INFLOW_PROXY',
            'ROTATION_OUTFLOW_PROXY',
            'MARKET_ACTIVITY_RISING',
            'MARKET_ACTIVITY_COOLING',
            'NO_CONFIRMATION',
            'INSUFFICIENT_PARTICIPATION',
            'DATA_UNAVAILABLE'
        ))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Deterministic research-only sector proxy-rotation snapshots; no account or execution semantics.';
