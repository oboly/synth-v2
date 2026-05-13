CREATE TABLE IF NOT EXISTS paper_advice_observation (
    paper_advice_observation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    policy_name VARCHAR(96) NOT NULL,
    policy_version VARCHAR(32) NOT NULL,

    asset_id BIGINT UNSIGNED NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    venue VARCHAR(32) NOT NULL,
    interval_code VARCHAR(16) NOT NULL,

    asof_ts_utc DATETIME(6) NOT NULL,
    context_ts_utc DATETIME(6) NOT NULL,

    selection_state VARCHAR(32) NULL,
    selection_bias VARCHAR(64) NULL,
    selection_score DECIMAL(20,10) NULL,
    priority_rank INT NULL,

    setup_filter_state VARCHAR(32) NULL,
    setup_filter_reason VARCHAR(128) NULL,
    current_target_horizon VARCHAR(32) NULL,
    policy_decision VARCHAR(64) NULL,
    suggested_horizon VARCHAR(32) NULL,
    allowed_now TINYINT(1) NULL,

    aplus_bucket VARCHAR(64) NULL,
    aplus_phase VARCHAR(32) NULL,
    aplus_coherence VARCHAR(32) NULL,
    aplus_field VARCHAR(32) NULL,
    aplus_geometry VARCHAR(32) NULL,
    aplus_structural_role VARCHAR(32) NULL,
    aplus_expansion_quality VARCHAR(32) NULL,
    aplus_anchor_strength VARCHAR(32) NULL,
    aplus_strategic_bias VARCHAR(32) NULL,

    leg_direction VARCHAR(16) NULL,
    entry_zone_low DECIMAL(28,12) NULL,
    entry_zone_high DECIMAL(28,12) NULL,
    entry_zone_type VARCHAR(64) NULL,
    tp_zone_low DECIMAL(28,12) NULL,
    tp_zone_high DECIMAL(28,12) NULL,
    tp_zone_type VARCHAR(64) NULL,
    invalidation_price DECIMAL(28,12) NULL,
    zone_confidence_score DECIMAL(12,8) NULL,
    zone_alignment_score DECIMAL(12,8) NULL,

    advice_state VARCHAR(64) NOT NULL,
    advice_action VARCHAR(96) NOT NULL,
    confidence_score DECIMAL(12,8) NOT NULL,
    risk_label VARCHAR(64) NOT NULL,

    reason_codes_json LONGTEXT NULL,
    source_ref_json LONGTEXT NULL,

    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (paper_advice_observation_id),

    UNIQUE KEY uq_paper_advice_observation (
        policy_name,
        policy_version,
        venue,
        interval_code,
        asof_ts_utc,
        asset_id
    ),

    KEY ix_paper_advice_latest (
        venue,
        interval_code,
        asof_ts_utc,
        advice_state,
        priority_rank
    ),

    KEY ix_paper_advice_symbol (
        symbol,
        asof_ts_utc
    ),

    KEY ix_paper_advice_state (
        advice_state,
        confidence_score
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
