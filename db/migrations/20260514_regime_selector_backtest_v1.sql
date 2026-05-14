-- regime_selector_backtest_observation_v1
--
-- Research-only. Market-only. Account-agnostic.
-- No account_id, no balances, no positions, no orders, no broker calls.
--
-- Purpose:
--   Store one row per (report, version, selector_mode, strategy_signature, asset, venue, interval, ts, horizon).
--
--   selector_mode identifies WHICH regime dimension is the active selector for that row:
--     GLOBAL             -> uses global_regime as primary dimension
--     ASSET_CLASS        -> uses asset_class_regime as primary dimension
--     GLOBAL_CLASS       -> uses global_class_regime (cross) as primary dimension
--     STRATEGY_SIGNATURE -> uses strategy_signature as primary dimension
--     EXPERIMENTAL       -> reserved for custom variants
--
--   strategy_signature combines selection_state + setup_filter + policy + advice + aplus_bucket.
--   It is always non-null. When optional tables are absent it contains UNKNOWN tokens.
--
--   All regime columns (global_regime, asset_class_regime, global_class_regime) are stored on
--   every row regardless of selector_mode, so any dimension can be queried independently.
--
--   The unique key is intentionally wide so that:
--     - Different selector_mode variants coexist (GLOBAL vs ASSET_CLASS vs GLOBAL_CLASS vs STRATEGY_SIGNATURE).
--     - Different report_version reruns coexist.
--     - Different strategy_signature values (strategy state changes) coexist.
--     - Reruns of the same (report, version, mode, signature, asset, venue, interval, ts, horizon)
--       overwrite via ON DUPLICATE KEY UPDATE rather than creating duplicates.
--
-- Downstream path (read-only from here):
--   regime_selector_backtest_v1
--   -> regime selector candidates
--   -> active_regime_observation design
--   -> policy_router design
--   -> optional selection/advice integration after validation
--
-- Do NOT add decision_gate, execution_planner, or executor logic here.
-- Paper/live parity is NOT a concern at this layer.

CREATE TABLE IF NOT EXISTS regime_selector_backtest_observation_v1 (
    regime_selector_backtest_observation_v1_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    -- Report identity
    report_name VARCHAR(128) NOT NULL,
    report_version VARCHAR(32) NOT NULL,
    run_ts_utc DATETIME(6) NOT NULL,

    -- Selector identity
    selector_mode VARCHAR(64) NOT NULL,

    -- Asset / market identity
    asset_id BIGINT UNSIGNED NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    venue VARCHAR(32) NOT NULL,
    interval_code VARCHAR(16) NOT NULL,
    asof_ts_utc DATETIME(6) NOT NULL,
    horizon_hours INT UNSIGNED NOT NULL,

    -- Price / forward outcome
    current_price DECIMAL(28,12) NULL,
    future_price DECIMAL(28,12) NULL,
    forward_return_pct DECIMAL(20,10) NULL,
    mfe_pct DECIMAL(20,10) NULL,
    mae_pct DECIMAL(20,10) NULL,

    -- Market context
    btc_return_24h_pct DECIMAL(20,10) NULL,
    btc_return_72h_pct DECIMAL(20,10) NULL,
    asset_return_24h_pct DECIMAL(20,10) NULL,
    class_return_24h_pct DECIMAL(20,10) NULL,
    relative_class_vs_btc_24h_pct DECIMAL(20,10) NULL,

    -- Regime classification (all dimensions stored regardless of selector_mode)
    asset_class VARCHAR(32) NULL,
    global_regime VARCHAR(64) NULL,
    asset_class_regime VARCHAR(64) NULL,
    global_class_regime VARCHAR(128) NULL,

    -- Strategy signature (NOT NULL — always has value; UNKNOWN tokens when optional tables absent)
    strategy_signature VARCHAR(255) NOT NULL,

    -- Selection state (from selection_state)
    selection_state VARCHAR(32) NULL,
    selection_bias VARCHAR(64) NULL,
    selection_score DECIMAL(20,10) NULL,
    priority_rank INT NULL,

    -- Strategy layer state (from optional tables; NULL when table absent)
    setup_filter_state VARCHAR(32) NULL,
    setup_filter_reason VARCHAR(128) NULL,
    policy_decision VARCHAR(64) NULL,
    advice_state VARCHAR(64) NULL,
    advice_action VARCHAR(96) NULL,
    aplus_bucket VARCHAR(64) NULL,

    -- Lineage / audit
    source_ref_json LONGTEXT NULL,

    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (regime_selector_backtest_observation_v1_id),

    -- Wide unique key: allows all selector variants to coexist; reruns overwrite cleanly.
    -- strategy_signature is NOT NULL so the constraint works without MySQL NULL-escape behaviour.
    UNIQUE KEY uq_regime_selector_backtest_v1 (
        report_name,
        report_version,
        selector_mode,
        strategy_signature,
        asset_id,
        venue,
        interval_code,
        asof_ts_utc,
        horizon_hours
    ),

    KEY ix_regime_selector_global_regime_v1 (
        global_regime,
        asof_ts_utc
    ),

    KEY ix_regime_selector_asset_class_regime_v1 (
        asset_class_regime,
        asof_ts_utc
    ),

    KEY ix_regime_selector_global_class_regime_v1 (
        global_class_regime,
        asof_ts_utc
    ),

    KEY ix_regime_selector_strategy_signature_v1 (
        strategy_signature,
        asof_ts_utc
    ),

    KEY ix_regime_selector_asof_ts_utc_v1 (
        asof_ts_utc,
        venue,
        interval_code
    )

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
