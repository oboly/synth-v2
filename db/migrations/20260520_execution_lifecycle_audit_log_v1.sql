CREATE TABLE IF NOT EXISTS decision_gate_audit_log (
    decision_gate_audit_log_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    user_id BIGINT UNSIGNED NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    strategy_profile_id BIGINT UNSIGNED NULL,
    strategy_candidate_id BIGINT UNSIGNED NULL,

    venue VARCHAR(32) NOT NULL,
    asset_id BIGINT UNSIGNED NOT NULL,
    symbol VARCHAR(32) NULL,
    interval_code VARCHAR(16) NOT NULL,

    execution_mode VARCHAR(32) NOT NULL,
    lifecycle_state VARCHAR(64) NULL,
    permission_state VARCHAR(64) NULL,
    decision_state VARCHAR(64) NULL,
    decision_reason VARCHAR(128) NULL,
    execution_intent VARCHAR(64) NULL,
    action_type VARCHAR(64) NULL,
    requested_side VARCHAR(16) NULL,
    requested_notional_eur DECIMAL(28,10) NULL,
    requested_quantity_base DECIMAL(28,10) NULL,
    limit_price DECIMAL(28,10) NULL,

    reason_codes_json LONGTEXT NULL,
    safety_markers_json LONGTEXT NULL,
    upstream_ref_type VARCHAR(64) NULL,
    upstream_ref_id VARCHAR(128) NULL,

    asof_ts_utc DATETIME(6) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (decision_gate_audit_log_id),

    KEY ix_decision_gate_audit_scope (
        trading_account_id,
        venue,
        asset_id,
        interval_code,
        asof_ts_utc
    ),

    KEY ix_decision_gate_audit_mode_state (
        execution_mode,
        decision_state,
        permission_state
    ),

    KEY ix_decision_gate_audit_created (
        created_ts_utc
    ),

    KEY ix_decision_gate_audit_upstream (
        upstream_ref_type,
        upstream_ref_id
    )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only account-scoped decision gate audit log. Does not grant execution permission or place orders.';

CREATE TABLE IF NOT EXISTS execution_plan_audit_log (
    execution_plan_audit_log_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    user_id BIGINT UNSIGNED NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    strategy_profile_id BIGINT UNSIGNED NULL,
    strategy_candidate_id BIGINT UNSIGNED NULL,

    venue VARCHAR(32) NOT NULL,
    asset_id BIGINT UNSIGNED NOT NULL,
    symbol VARCHAR(32) NULL,
    interval_code VARCHAR(16) NOT NULL,

    execution_plan_id BIGINT UNSIGNED NULL,
    execution_mode VARCHAR(32) NOT NULL,
    lifecycle_state VARCHAR(64) NULL,
    permission_state VARCHAR(64) NULL,
    plan_state VARCHAR(64) NULL,
    planner_name VARCHAR(96) NULL,
    planner_version VARCHAR(32) NULL,
    action_type VARCHAR(64) NULL,
    requested_side VARCHAR(16) NULL,
    requested_notional_eur DECIMAL(28,10) NULL,
    requested_quantity_base DECIMAL(28,10) NULL,
    limit_price DECIMAL(28,10) NULL,

    reason_codes_json LONGTEXT NULL,
    safety_markers_json LONGTEXT NULL,
    upstream_ref_type VARCHAR(64) NULL,
    upstream_ref_id VARCHAR(128) NULL,

    asof_ts_utc DATETIME(6) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (execution_plan_audit_log_id),

    KEY ix_execution_plan_audit_scope (
        trading_account_id,
        venue,
        asset_id,
        interval_code,
        asof_ts_utc
    ),

    KEY ix_execution_plan_audit_plan (
        execution_plan_id,
        plan_state
    ),

    KEY ix_execution_plan_audit_mode_state (
        execution_mode,
        permission_state,
        plan_state
    ),

    KEY ix_execution_plan_audit_created (
        created_ts_utc
    ),

    KEY ix_execution_plan_audit_upstream (
        upstream_ref_type,
        upstream_ref_id
    )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only account-scoped execution planner audit log. Records plan intent only; does not submit orders.';

CREATE TABLE IF NOT EXISTS executor_action_audit_log (
    executor_action_audit_log_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    user_id BIGINT UNSIGNED NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    strategy_profile_id BIGINT UNSIGNED NULL,
    strategy_candidate_id BIGINT UNSIGNED NULL,

    venue VARCHAR(32) NOT NULL,
    asset_id BIGINT UNSIGNED NOT NULL,
    symbol VARCHAR(32) NULL,
    interval_code VARCHAR(16) NOT NULL,

    execution_plan_id BIGINT UNSIGNED NULL,
    execution_mode VARCHAR(32) NOT NULL,
    lifecycle_state VARCHAR(64) NULL,
    permission_state VARCHAR(64) NULL,
    action_type VARCHAR(64) NULL,
    requested_side VARCHAR(16) NULL,
    requested_notional_eur DECIMAL(28,10) NULL,
    requested_quantity_base DECIMAL(28,10) NULL,
    limit_price DECIMAL(28,10) NULL,
    submitted TINYINT(1) NOT NULL DEFAULT 0,
    broker_adapter_name VARCHAR(96) NULL,
    broker_request_json LONGTEXT NULL,

    reason_codes_json LONGTEXT NULL,
    safety_markers_json LONGTEXT NULL,
    upstream_ref_type VARCHAR(64) NULL,
    upstream_ref_id VARCHAR(128) NULL,

    asof_ts_utc DATETIME(6) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (executor_action_audit_log_id),

    KEY ix_executor_action_audit_scope (
        trading_account_id,
        venue,
        asset_id,
        interval_code,
        asof_ts_utc
    ),

    KEY ix_executor_action_audit_plan (
        execution_plan_id,
        action_type
    ),

    KEY ix_executor_action_audit_mode_state (
        execution_mode,
        permission_state,
        submitted
    ),

    KEY ix_executor_action_audit_created (
        created_ts_utc
    ),

    KEY ix_executor_action_audit_upstream (
        upstream_ref_type,
        upstream_ref_id
    )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only account-scoped executor action audit log. LIVE order submission remains disabled unless later hard-gated runtime is added.';

CREATE TABLE IF NOT EXISTS executor_result_audit_log (
    executor_result_audit_log_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    user_id BIGINT UNSIGNED NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    strategy_profile_id BIGINT UNSIGNED NULL,
    strategy_candidate_id BIGINT UNSIGNED NULL,

    venue VARCHAR(32) NOT NULL,
    asset_id BIGINT UNSIGNED NOT NULL,
    symbol VARCHAR(32) NULL,
    interval_code VARCHAR(16) NOT NULL,

    executor_action_audit_log_id BIGINT UNSIGNED NULL,
    execution_plan_id BIGINT UNSIGNED NULL,
    execution_mode VARCHAR(32) NOT NULL,
    lifecycle_state VARCHAR(64) NULL,
    permission_state VARCHAR(64) NULL,
    action_type VARCHAR(64) NULL,
    result_state VARCHAR(64) NULL,
    requested_side VARCHAR(16) NULL,
    requested_notional_eur DECIMAL(28,10) NULL,
    requested_quantity_base DECIMAL(28,10) NULL,
    limit_price DECIMAL(28,10) NULL,
    submitted TINYINT(1) NOT NULL DEFAULT 0,
    filled_quantity_base DECIMAL(28,10) NULL,
    filled_notional_eur DECIMAL(28,10) NULL,
    broker_response_json LONGTEXT NULL,
    error_code VARCHAR(96) NULL,
    error_message VARCHAR(512) NULL,

    reason_codes_json LONGTEXT NULL,
    safety_markers_json LONGTEXT NULL,
    upstream_ref_type VARCHAR(64) NULL,
    upstream_ref_id VARCHAR(128) NULL,

    asof_ts_utc DATETIME(6) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (executor_result_audit_log_id),

    KEY ix_executor_result_audit_scope (
        trading_account_id,
        venue,
        asset_id,
        interval_code,
        asof_ts_utc
    ),

    KEY ix_executor_result_audit_action (
        executor_action_audit_log_id,
        result_state
    ),

    KEY ix_executor_result_audit_plan (
        execution_plan_id,
        result_state
    ),

    KEY ix_executor_result_audit_mode_state (
        execution_mode,
        permission_state,
        submitted
    ),

    KEY ix_executor_result_audit_created (
        created_ts_utc
    ),

    KEY ix_executor_result_audit_upstream (
        upstream_ref_type,
        upstream_ref_id
    )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only account-scoped executor result audit log for simulated or future broker results. This migration does not enable live trading.';
