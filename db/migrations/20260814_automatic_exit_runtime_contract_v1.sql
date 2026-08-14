-- Phase 4A: automatic-exit runtime inputs and append-only evaluation evidence.
-- This migration grants no executor, broker, credential, order, or LIVE authority.

CREATE TABLE IF NOT EXISTS automatic_exit_account_permission_v1 (
    automatic_exit_account_permission_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    planning_enabled TINYINT(1) NOT NULL DEFAULT 0,
    effective_from_ts_utc DATETIME(6) NOT NULL,
    effective_until_ts_utc DATETIME(6) NULL,
    permission_version VARCHAR(32) NOT NULL DEFAULT '1',
    source_provenance VARCHAR(128) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (automatic_exit_account_permission_id),
    KEY ix_automatic_exit_permission_lookup (trading_account_id, effective_from_ts_utc),
    CONSTRAINT fk_automatic_exit_permission_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT chk_automatic_exit_permission_enabled CHECK (planning_enabled IN (0, 1)),
    CONSTRAINT chk_automatic_exit_permission_window CHECK (
        effective_until_ts_utc IS NULL OR effective_until_ts_utc > effective_from_ts_utc
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only account-scoped automatic-exit planning opt-in. No row means disabled; this is not LIVE or order authority.';

CREATE TABLE IF NOT EXISTS account_open_order_snapshot_run_v1 (
    account_open_order_snapshot_run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    source_name VARCHAR(96) NOT NULL,
    snapshot_ts_utc DATETIME(6) NOT NULL,
    snapshot_state VARCHAR(32) NOT NULL,
    open_order_count INT UNSIGNED NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (account_open_order_snapshot_run_id),
    UNIQUE KEY uq_account_open_order_snapshot_run (trading_account_id, venue, source_name, snapshot_ts_utc),
    KEY ix_account_open_order_snapshot_run_latest (trading_account_id, venue, snapshot_ts_utc),
    CONSTRAINT fk_account_open_order_snapshot_run_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT chk_account_open_order_snapshot_run_state CHECK (snapshot_state = 'COMPLETE')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only complete open-order snapshot header. A zero count is authoritative only with this row; producer integration is separately owned.';

CREATE TABLE IF NOT EXISTS automatic_exit_profile_v1 (
    automatic_exit_profile_row_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    profile_id VARCHAR(128) NOT NULL,
    profile_version VARCHAR(32) NOT NULL,
    venue VARCHAR(32) NOT NULL,
    asset_id BIGINT UNSIGNED NOT NULL,
    market VARCHAR(64) NOT NULL,
    active_target_price DECIMAL(36,18) NULL,
    invalidation_price DECIMAL(36,18) NULL,
    evidence_id VARCHAR(128) NOT NULL,
    evidence_provenance VARCHAR(256) NOT NULL,
    observed_ts_utc DATETIME(6) NOT NULL,
    effective_from_ts_utc DATETIME(6) NOT NULL,
    effective_until_ts_utc DATETIME(6) NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (automatic_exit_profile_row_id),
    UNIQUE KEY uq_automatic_exit_profile_revision (profile_id, profile_version),
    KEY ix_automatic_exit_profile_lookup (venue, asset_id, market, effective_from_ts_utc),
    CONSTRAINT fk_automatic_exit_profile_asset FOREIGN KEY (asset_id) REFERENCES asset (asset_id),
    CONSTRAINT chk_automatic_exit_profile_prices CHECK (
        (active_target_price IS NOT NULL OR invalidation_price IS NOT NULL)
        AND (active_target_price IS NULL OR active_target_price > 0)
        AND (invalidation_price IS NULL OR invalidation_price > 0)
    ),
    CONSTRAINT chk_automatic_exit_profile_window CHECK (
        effective_until_ts_utc IS NULL OR effective_until_ts_utc > effective_from_ts_utc
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only market-level automatic-exit policy profile. It contains no account permission, quantity, ladder, or broker state.';

CREATE TABLE IF NOT EXISTS automatic_exit_evaluation_audit_v1 (
    automatic_exit_evaluation_audit_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    idempotency_key CHAR(64) NOT NULL,
    runtime_version VARCHAR(64) NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    position_reference VARCHAR(128) NOT NULL,
    venue VARCHAR(32) NOT NULL,
    asset_id BIGINT UNSIGNED NOT NULL,
    market VARCHAR(64) NOT NULL,
    source_evidence_json LONGTEXT NOT NULL CHECK (JSON_VALID(source_evidence_json)),
    candidate_state VARCHAR(32) NOT NULL,
    candidate_action VARCHAR(16) NULL,
    candidate_reason_code VARCHAR(128) NOT NULL,
    candidate_evidence_id VARCHAR(128) NULL,
    exit_profile_id VARCHAR(128) NULL,
    exit_profile_version VARCHAR(32) NULL,
    gate_state VARCHAR(32) NULL,
    gate_reason_code VARCHAR(128) NULL,
    approved_fraction_candidate DECIMAL(30,18) NULL,
    approved_quantity_ceiling_base DECIMAL(36,18) NULL,
    planner_state VARCHAR(32) NOT NULL,
    planner_reason_code VARCHAR(256) NULL,
    immutable_plan_json LONGTEXT NULL CHECK (immutable_plan_json IS NULL OR JSON_VALID(immutable_plan_json)),
    evaluation_ts_utc DATETIME(6) NOT NULL,
    planning_ts_utc DATETIME(6) NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (automatic_exit_evaluation_audit_id),
    UNIQUE KEY uq_automatic_exit_evaluation_idempotency (idempotency_key),
    KEY ix_automatic_exit_evaluation_scope (trading_account_id, position_reference, venue, asset_id, market, evaluation_ts_utc),
    CONSTRAINT fk_automatic_exit_evaluation_account FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT fk_automatic_exit_evaluation_asset FOREIGN KEY (asset_id) REFERENCES asset (asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only Phase-4 automatic-exit candidate/gate/planner evidence. Immutable staged plans are audit-only and never executor input.';
