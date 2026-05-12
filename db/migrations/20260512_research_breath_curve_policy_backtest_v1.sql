CREATE TABLE IF NOT EXISTS research_breath_curve_policy_run (
    research_breath_curve_policy_run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_ts_utc DATETIME(6) NOT NULL DEFAULT UTC_TIMESTAMP(6),
    policy_name VARCHAR(128) NOT NULL,
    policy_version VARCHAR(32) NOT NULL,
    source_name VARCHAR(128) NOT NULL,
    source_path VARCHAR(512) NULL,
    checkpoint_set VARCHAR(128) NOT NULL,
    min_partial_score DECIMAL(18,8) NOT NULL,
    tp1_weight DECIMAL(18,8) NOT NULL,
    tp2_weight DECIMAL(18,8) NOT NULL,
    cost_bps DECIMAL(18,8) NOT NULL DEFAULT 0.00000000,
    require_offset_match TINYINT(1) NOT NULL DEFAULT 0,
    rows_input INT UNSIGNED NOT NULL DEFAULT 0,
    rows_written INT UNSIGNED NOT NULL DEFAULT 0,
    notes VARCHAR(512) NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT UTC_TIMESTAMP(6),

    PRIMARY KEY (research_breath_curve_policy_run_id),

    KEY idx_research_breath_policy_run_name_ts_v1 (
        policy_name,
        run_ts_utc
    ),

    KEY idx_research_breath_policy_run_source_v1 (
        source_name,
        run_ts_utc
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS research_breath_curve_policy_result (
    research_breath_curve_policy_result_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    research_breath_curve_policy_run_id BIGINT UNSIGNED NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    anchor_date DATE NOT NULL,
    checkpoint_ratio DECIMAL(10,6) NOT NULL,
    selected_partial_offset_days DECIMAL(10,4) NULL,
    selected_partial_score DECIMAL(18,8) NULL,
    selected_partial_shape DECIMAL(18,8) NULL,
    selected_partial_timing DECIMAL(18,8) NULL,
    selected_partial_coverage DECIMAL(18,8) NULL,
    selected_partial_due_markers INT NULL,
    selected_partial_observed_markers INT NULL,
    offset_matches_best_full TINYINT(1) NOT NULL DEFAULT 0,
    return_to_1000_pct DECIMAL(18,8) NULL,
    return_to_1272_pct DECIMAL(18,8) NULL,
    policy_return_pct DECIMAL(18,8) NOT NULL,
    policy_state VARCHAR(64) NOT NULL,
    source_row_json LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (JSON_VALID(source_row_json)),
    created_ts_utc DATETIME(6) NOT NULL DEFAULT UTC_TIMESTAMP(6),

    PRIMARY KEY (research_breath_curve_policy_result_id),

    KEY idx_research_breath_policy_result_run_v1 (
        research_breath_curve_policy_run_id
    ),

    KEY idx_research_breath_policy_result_symbol_v1 (
        symbol,
        checkpoint_ratio,
        policy_return_pct
    ),

    KEY idx_research_breath_policy_result_checkpoint_v1 (
        checkpoint_ratio,
        policy_return_pct
    ),

    CONSTRAINT fk_research_breath_policy_result_run_v1
        FOREIGN KEY (research_breath_curve_policy_run_id)
        REFERENCES research_breath_curve_policy_run (research_breath_curve_policy_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
