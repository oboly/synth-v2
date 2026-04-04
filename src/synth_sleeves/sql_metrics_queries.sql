-- Closed trades for one UTC date
SELECT
    DATE(close_ts_utc) AS metric_date_utc,
    sleeve_code,
    strategy_name,
    strategy_version_id,
    realized_pnl_eur,
    realized_pnl_pct,
    holding_minutes
FROM trade_lot
WHERE DATE(close_ts_utc) = %s;

-- PREPARE transitions for one UTC date
SELECT
    DATE(created_ts_utc) AS metric_date_utc,
    sleeve_code,
    strategy_name,
    NULL AS strategy_version_id,
    from_state,
    to_state,
    transition_count
FROM state_transition_daily
WHERE metric_date_utc = %s
  AND from_state = 'PREPARE';
