-- Seed: PAPER / paper_tactical_baseline
-- Purpose:
--   Reproducible DB-backed config for TACTICAL_PULSE paper/live-paper cycles.
-- Target DB:
--   synth_bt
-- Safe to re-run:
--   yes, idempotent via ON DUPLICATE KEY UPDATE.

INSERT INTO config_set (
    config_name,
    scope,
    is_active,
    description
) VALUES (
    'paper_tactical_baseline',
    'PAPER',
    1,
    'Baseline paper/live-paper settings for TACTICAL_PULSE sleeve.'
)
ON DUPLICATE KEY UPDATE
    is_active = VALUES(is_active),
    description = VALUES(description),
    updated_ts_utc = UTC_TIMESTAMP(6);

SET @paper_tactical_config_set_id := (
    SELECT config_set_id
    FROM config_set
    WHERE scope = 'PAPER'
      AND config_name = 'paper_tactical_baseline'
    LIMIT 1
);

INSERT INTO config_param (
    config_set_id,
    component,
    parameter_name,
    value_text,
    value_type
) VALUES
    (@paper_tactical_config_set_id, 'entry_cooldown', 'cooldown_candles', '2', 'INT'),

    (@paper_tactical_config_set_id, 'exit_policy', 'stop_loss_pct', '0.010000', 'DECIMAL'),
    (@paper_tactical_config_set_id, 'exit_policy', 'take_profit_pct', '0.020000', 'DECIMAL'),

    (@paper_tactical_config_set_id, 'planner', 'execute_target_fraction', '0.06600000', 'DECIMAL'),
    (@paper_tactical_config_set_id, 'planner', 'max_chase_bps', '15.00000000', 'DECIMAL'),
    (@paper_tactical_config_set_id, 'planner', 'max_notional_eur', '25.0000000000', 'DECIMAL'),
    (@paper_tactical_config_set_id, 'planner', 'max_reprices', '5', 'INT'),
    (@paper_tactical_config_set_id, 'planner', 'max_wait_seconds', '1800', 'INT'),
    (@paper_tactical_config_set_id, 'planner', 'min_spread_bps_for_capture', '3.00000000', 'DECIMAL'),
    (@paper_tactical_config_set_id, 'planner', 'prepare_target_fraction', '0.06600000', 'DECIMAL'),

    (@paper_tactical_config_set_id, 'selection', 'buy_ready_max_rank', '5', 'INT'),
    (@paper_tactical_config_set_id, 'selection', 'buy_ready_min_score', '0.60', 'DECIMAL'),
    (@paper_tactical_config_set_id, 'selection', 'prepare_min_score', '0.52', 'DECIMAL')
ON DUPLICATE KEY UPDATE
    value_text = VALUES(value_text),
    value_type = VALUES(value_type),
    updated_ts_utc = UTC_TIMESTAMP(6);
