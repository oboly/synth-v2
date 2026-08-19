-- Issue #399 Phase 4: automatic BUY runtime input snapshots and append-only audit.
-- Migration artifact only. Grants no executor, broker, credential, order, or LIVE authority.

CREATE TABLE IF NOT EXISTS automatic_buy_runtime_input_v1 (
    automatic_buy_runtime_input_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source_snapshot_key CHAR(64) NOT NULL,
    input_contract_version VARCHAR(16) NOT NULL DEFAULT '1',
    input_state VARCHAR(16) NOT NULL DEFAULT 'READY',
    trading_account_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    asset_id BIGINT UNSIGNED NOT NULL,
    market VARCHAR(64) NOT NULL,
    strategy_bucket_id VARCHAR(64) NOT NULL,
    strategy_id VARCHAR(128) NOT NULL,
    strategy_version VARCHAR(64) NOT NULL,
    setup_id VARCHAR(128) NOT NULL,
    setup_ready TINYINT(1) NOT NULL,
    current_price DECIMAL(36,18) NOT NULL,
    entry_zone_low DECIMAL(36,18) NULL,
    entry_zone_high DECIMAL(36,18) NULL,
    re_entry_zone_low DECIMAL(36,18) NULL,
    re_entry_zone_high DECIMAL(36,18) NULL,
    setup_evidence_id VARCHAR(128) NOT NULL,
    setup_observed_ts_utc DATETIME(6) NOT NULL,
    account_observed_ts_utc DATETIME(6) NOT NULL,
    account_enabled TINYINT(1) NOT NULL,
    account_mode VARCHAR(16) NOT NULL,
    automatic_buy_execution_enabled TINYINT(1) NOT NULL,
    free_quote_balance_eur DECIMAL(36,18) NOT NULL,
    free_quote_balance_observed_ts_utc DATETIME(6) NOT NULL,
    blocking_conflict TINYINT(1) NOT NULL,
    proposed_position_amount_eur DECIMAL(36,18) NOT NULL,
    current_bucket_amount_eur DECIMAL(36,18) NOT NULL,
    current_open_positions INT UNSIGNED NOT NULL,
    current_asset_exposure_pct DECIMAL(9,6) NOT NULL,
    max_automatic_buy_notional_eur DECIMAL(36,18) NULL,
    source_provenance VARCHAR(256) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (automatic_buy_runtime_input_id),
    UNIQUE KEY uq_automatic_buy_runtime_source_snapshot (source_snapshot_key),
    KEY ix_automatic_buy_runtime_ready (input_state, venue, automatic_buy_runtime_input_id),
    KEY ix_automatic_buy_runtime_account (trading_account_id, market, setup_observed_ts_utc),
    CONSTRAINT fk_automatic_buy_runtime_input_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT fk_automatic_buy_runtime_input_asset
        FOREIGN KEY (asset_id) REFERENCES asset (asset_id),
    CONSTRAINT chk_automatic_buy_runtime_input_state CHECK (input_state = 'READY'),
    CONSTRAINT chk_automatic_buy_runtime_input_flags CHECK (
        setup_ready IN (0,1) AND account_enabled IN (0,1)
        AND automatic_buy_execution_enabled IN (0,1) AND blocking_conflict IN (0,1)
    ),
    CONSTRAINT chk_automatic_buy_runtime_input_amounts CHECK (
        current_price > 0
        AND free_quote_balance_eur >= 0
        AND proposed_position_amount_eur > 0
        AND current_bucket_amount_eur >= 0
        AND current_asset_exposure_pct >= 0 AND current_asset_exposure_pct <= 100
        AND (max_automatic_buy_notional_eur IS NULL OR max_automatic_buy_notional_eur >= 0)
    ),
    CONSTRAINT chk_automatic_buy_runtime_entry_zone CHECK (
        (entry_zone_low IS NULL OR entry_zone_low > 0)
        AND (entry_zone_high IS NULL OR entry_zone_high > 0)
        AND (entry_zone_low IS NULL OR entry_zone_high IS NULL OR entry_zone_high >= entry_zone_low)
    ),
    CONSTRAINT chk_automatic_buy_runtime_reentry_zone CHECK (
        (re_entry_zone_low IS NULL OR re_entry_zone_low > 0)
        AND (re_entry_zone_high IS NULL OR re_entry_zone_high > 0)
        AND (re_entry_zone_low IS NULL OR re_entry_zone_high IS NULL OR re_entry_zone_high >= re_entry_zone_low)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only exact input snapshot for automatic BUY Phase 4 runtime. No executor/order authority.';

DELIMITER //
CREATE TRIGGER trg_automatic_buy_runtime_input_no_update
BEFORE UPDATE ON automatic_buy_runtime_input_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic BUY runtime input is append-only';
END//
CREATE TRIGGER trg_automatic_buy_runtime_input_no_delete
BEFORE DELETE ON automatic_buy_runtime_input_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic BUY runtime input is append-only';
END//
DELIMITER ;

CREATE TABLE IF NOT EXISTS automatic_buy_evaluation_audit_v1 (
    automatic_buy_evaluation_audit_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    idempotency_key CHAR(64) NOT NULL,
    runtime_version VARCHAR(64) NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    asset_id BIGINT UNSIGNED NOT NULL,
    market VARCHAR(64) NOT NULL,
    source_evidence_json LONGTEXT NOT NULL CHECK (JSON_VALID(source_evidence_json)),
    candidate_state VARCHAR(32) NOT NULL,
    candidate_action VARCHAR(16) NULL,
    candidate_reason_code VARCHAR(128) NOT NULL,
    candidate_evidence_id VARCHAR(128) NULL,
    gate_state VARCHAR(32) NULL,
    gate_reason_code VARCHAR(128) NULL,
    approved_notional_ceiling_eur DECIMAL(36,18) NULL,
    strategy_bucket_reason_code VARCHAR(128) NULL,
    protection_code VARCHAR(64) NULL,
    protection_reason_code VARCHAR(128) NULL,
    planner_state VARCHAR(32) NOT NULL,
    planner_reason_code VARCHAR(256) NULL,
    immutable_plan_json LONGTEXT NULL CHECK (immutable_plan_json IS NULL OR JSON_VALID(immutable_plan_json)),
    evaluation_ts_utc DATETIME(6) NOT NULL,
    planning_ts_utc DATETIME(6) NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (automatic_buy_evaluation_audit_id),
    UNIQUE KEY uq_automatic_buy_evaluation_idempotency (idempotency_key),
    KEY ix_automatic_buy_evaluation_scope (trading_account_id, venue, asset_id, market, evaluation_ts_utc),
    CONSTRAINT fk_automatic_buy_evaluation_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT fk_automatic_buy_evaluation_asset
        FOREIGN KEY (asset_id) REFERENCES asset (asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only automatic BUY candidate/gate/planner evidence. Immutable plan JSON is audit-only, never executor input.';

DELIMITER //
CREATE TRIGGER trg_automatic_buy_evaluation_audit_no_update
BEFORE UPDATE ON automatic_buy_evaluation_audit_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic BUY evaluation audit is append-only';
END//
CREATE TRIGGER trg_automatic_buy_evaluation_audit_no_delete
BEFORE DELETE ON automatic_buy_evaluation_audit_v1
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'automatic BUY evaluation audit is append-only';
END//
DELIMITER ;
