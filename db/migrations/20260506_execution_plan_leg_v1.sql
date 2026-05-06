CREATE TABLE IF NOT EXISTS execution_plan_leg (
    execution_plan_leg_id BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
    execution_plan_id BIGINT(20) UNSIGNED NOT NULL,

    leg_index INT(11) NOT NULL,
    side VARCHAR(8) NOT NULL,
    leg_type VARCHAR(32) NOT NULL,

    target_price_eur DECIMAL(28,10) DEFAULT NULL,
    target_fraction DECIMAL(18,8) NOT NULL DEFAULT 0.00000000,
    target_notional_eur DECIMAL(28,10) DEFAULT NULL,
    quantity_base DECIMAL(28,10) DEFAULT NULL,

    post_only TINYINT(1) NOT NULL DEFAULT 1,
    time_in_force VARCHAR(16) NOT NULL DEFAULT 'GTC',

    max_reprices INT(11) NOT NULL DEFAULT 0,
    max_wait_seconds INT(11) NOT NULL DEFAULT 0,
    max_chase_bps DECIMAL(18,8) NOT NULL DEFAULT 0.00000000,
    min_spread_bps_for_capture DECIMAL(18,8) NOT NULL DEFAULT 0.00000000,
    escalation_to_urgent_limit TINYINT(1) NOT NULL DEFAULT 0,
    abort_if_signal_invalidates TINYINT(1) NOT NULL DEFAULT 1,

    leg_state VARCHAR(32) NOT NULL DEFAULT 'IDLE',
    notes VARCHAR(512) DEFAULT NULL,

    created_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    updated_ts_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP() ON UPDATE CURRENT_TIMESTAMP(),

    PRIMARY KEY (execution_plan_leg_id),

    UNIQUE KEY uq_execution_plan_leg_order (
        execution_plan_id,
        leg_index
    ),

    KEY ix_execution_plan_leg_plan_state (
        execution_plan_id,
        leg_state
    ),

    KEY ix_execution_plan_leg_state (
        leg_state
    ),

    KEY ix_execution_plan_leg_side_state (
        side,
        leg_state
    ),

    CONSTRAINT fk_execution_plan_leg_plan
        FOREIGN KEY (execution_plan_id)
        REFERENCES execution_plan (execution_plan_id)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Child table for multi-leg execution plans. Stores planner-created passive/urgent ladder legs; executor may later read legs but must not infer strategy or profile logic.';
