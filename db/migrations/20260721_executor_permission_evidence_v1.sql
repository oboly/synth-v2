-- Migration: executor_permission_evidence_v1
-- Boundary: additive permission-consumption evidence only.
-- Purpose: store exact decision_gate permission records consumed by executor
--          before any live broker write.
-- Non-goals: no credential binding, no decrypted credentials, no broker calls,
--            no order submission, no execution_plan overloading.

CREATE TABLE IF NOT EXISTS execution_permission_evidence (
    execution_permission_evidence_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    decision_gate_audit_log_id BIGINT UNSIGNED NULL,
    execution_plan_id BIGINT UNSIGNED NOT NULL,
    trading_account_id BIGINT UNSIGNED NOT NULL,

    venue VARCHAR(32) NOT NULL,
    asset_id BIGINT UNSIGNED NOT NULL,
    market VARCHAR(32) NOT NULL,

    execution_intent VARCHAR(64) NOT NULL,
    action_type VARCHAR(64) NOT NULL,
    requested_side VARCHAR(16) NULL,

    permission_state VARCHAR(64) NOT NULL,
    decision_state VARCHAR(64) NOT NULL,
    evidence_state VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',

    permitted_ts_utc DATETIME(6) NOT NULL,
    valid_until_ts_utc DATETIME(6) NOT NULL,
    revoked_ts_utc DATETIME(6) NULL,
    superseded_by_evidence_id BIGINT UNSIGNED NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (execution_permission_evidence_id),

    KEY ix_epe_plan_state_v1 (
        execution_plan_id,
        evidence_state,
        valid_until_ts_utc
    ),

    KEY ix_epe_account_scope_v1 (
        trading_account_id,
        venue,
        asset_id,
        market,
        evidence_state
    ),

    KEY ix_epe_decision_gate_audit_v1 (
        decision_gate_audit_log_id
    ),

    KEY ix_epe_superseded_by_v1 (
        superseded_by_evidence_id
    ),

    CONSTRAINT chk_epe_state_v1
        CHECK (evidence_state IN ('ACTIVE', 'REVOKED', 'SUPERSEDED')),

    CONSTRAINT chk_epe_permission_v1
        CHECK (permission_state IN ('EXECUTION_PERMITTED', 'EXECUTION_DENIED')),

    CONSTRAINT chk_epe_decision_v1
        CHECK (decision_state <> ''),

    CONSTRAINT fk_epe_decision_gate_audit_v1
        FOREIGN KEY (decision_gate_audit_log_id)
        REFERENCES decision_gate_audit_log (decision_gate_audit_log_id),

    CONSTRAINT fk_epe_execution_plan_v1
        FOREIGN KEY (execution_plan_id)
        REFERENCES execution_plan (execution_plan_id),

    CONSTRAINT fk_epe_trading_account_v1
        FOREIGN KEY (trading_account_id)
        REFERENCES trading_account (trading_account_id),

    CONSTRAINT fk_epe_superseded_by_v1
        FOREIGN KEY (superseded_by_evidence_id)
        REFERENCES execution_permission_evidence (execution_permission_evidence_id)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only decision_gate permission evidence consumed by executor. Credentials authenticate broker requests but do not authorize execution.';
