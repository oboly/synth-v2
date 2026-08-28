CREATE TABLE IF NOT EXISTS research_entry_quality_shadow (
    shadow_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asset_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    asof_ts_utc DATETIME(6) NOT NULL,
    evidence_key CHAR(64) NOT NULL,

    quality_ts_1d_utc DATETIME(6) NOT NULL,
    quality_ts_4h_utc DATETIME(6) NOT NULL,
    quality_ts_1h_utc DATETIME(6) NOT NULL,
    signal_ts_1d_utc DATETIME(6) NOT NULL,
    signal_ts_4h_utc DATETIME(6) NOT NULL,
    signal_ts_1h_utc DATETIME(6) NOT NULL,

    selection_engine_name VARCHAR(64) NOT NULL,
    selection_engine_version VARCHAR(32) NOT NULL,
    cq_model_version VARCHAR(32) NOT NULL,

    trade_quality_score DECIMAL(12,6) NULL,
    selection_score DECIMAL(12,6) NULL,
    timing_refinement_score DECIMAL(12,6) NULL,
    quality_penalty DECIMAL(12,6) NULL,
    quality_status_1d VARCHAR(32) NOT NULL,
    quality_status_4h VARCHAR(32) NOT NULL,
    quality_status_1h VARCHAR(32) NOT NULL,

    entry_quality_score DECIMAL(12,6) NULL,
    entry_quality_state VARCHAR(16) NOT NULL,
    reasons_json JSON NOT NULL,
    blockers_json JSON NOT NULL,

    ppp_pct DECIMAL(18,8) NULL,
    ppp_kind VARCHAR(32) NULL,
    ppp_source_ref VARCHAR(255) NULL,
    entry_strength DECIMAL(18,8) NULL,

    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (shadow_id),
    UNIQUE KEY uq_research_entry_quality_shadow (
        asset_id,
        venue,
        evidence_key,
        cq_model_version
    ),
    KEY ix_research_entry_quality_shadow_asof (asof_ts_utc),
    KEY ix_research_entry_quality_shadow_score (entry_quality_score),
    KEY ix_research_entry_quality_shadow_strength (entry_strength)
);

-- Research/shadow-only contract.
-- evidence_key fingerprints all 1d/4h/1h quality and signal source timestamps.
-- asof_ts_utc is the maximum timestamp in that evidence set, never runner wall time.
-- A changed source timestamp necessarily creates a distinct research observation identity.
-- This table is not an input to decision_gate, execution_planner, executor,
-- broker/order handling, or current production selection ranking.
