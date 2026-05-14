-- Migration: policy_router_preview_observation
-- Boundary: market-only · account-agnostic · no paper/live · no broker/order fields
-- Row grain: one row per (venue, interval_code, asof_ts_utc, asset_id, route_version)
-- H1 context only. Preview only. No decision_gate. No execution intent.

CREATE TABLE IF NOT EXISTS policy_router_preview_observation (
    policy_router_preview_observation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue         VARCHAR(32)  NOT NULL,
    interval_code VARCHAR(16)  NOT NULL,
    asof_ts_utc   DATETIME(6)  NOT NULL,

    -- Asset dimension (one row per asset per snapshot)
    asset_id    BIGINT UNSIGNED NOT NULL,
    symbol      VARCHAR(32)     NOT NULL,
    asset_class VARCHAR(32)     NOT NULL,

    -- Source links (read reference only — no routing authority)
    source_active_regime_observation_id BIGINT UNSIGNED NULL COMMENT 'FK-style ref to active_regime_observation',
    source_selection_state_ref_json     LONGTEXT NULL COMMENT 'selection_state snapshot ref, read-only',
    source_strategy_state_ref_json      LONGTEXT NULL COMMENT 'optional strategy state ref, read-only',

    -- Route output
    route_code              VARCHAR(96)   NOT NULL,
    route_version           VARCHAR(32)   NOT NULL,
    route_status            VARCHAR(64)   NOT NULL,
    route_confidence        DECIMAL(10,6) NULL,
    route_reason_codes_json LONGTEXT      NULL,

    -- Regime context (propagated from active_regime_observation)
    global_regime                  VARCHAR(64)  NOT NULL,
    asset_class_regime             VARCHAR(64)  NOT NULL,
    global_class_regime            VARCHAR(128) NOT NULL,
    validated_hypothesis_tags_json LONGTEXT     NULL,

    -- Policy family candidates (conceptual only — not permission, not intent)
    allowed_policy_family_json LONGTEXT NULL,
    blocked_policy_family_json LONGTEXT NULL,

    -- Audit
    source_ref_json LONGTEXT    NULL,
    created_ts_utc  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_policy_router_preview (
        venue, interval_code, asof_ts_utc, asset_id, route_version
    ),

    INDEX idx_asof         (asof_ts_utc, venue, interval_code),
    INDEX idx_route_code   (route_code, asof_ts_utc),
    INDEX idx_route_status (route_status, asof_ts_utc),
    INDEX idx_global       (global_regime, asof_ts_utc),
    INDEX idx_class_regime (asset_class_regime, asof_ts_utc),
    INDEX idx_asset_class  (asset_class, asof_ts_utc)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Market-only policy router preview. Account-agnostic. No paper/live. No orders. No execution intent.';
