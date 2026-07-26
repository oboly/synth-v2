-- Migration: manual_execution_request_v1
-- Boundary: schema only · additive only · no broker writes · no order submission
--           · no mutation of existing tables · no decision_gate/execution_planner
--           runtime change · no executor · no live execution enablement
-- Status:   CREATED BUT NOT APPLIED as of 2026-07-26. See
--           docs/reviews/manual_execution_ladder_p0_remediation_implementation_20260726.md
--           for compatibility notes and the exact evidence this was not run
--           against any database this session.
-- Purpose:  the canonical immutable manual_execution_request parent named
--           missing in
--           docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
--           finding F12, docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md
--           backlog item 7, and
--           docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md
--           finding B1 ("no authoritative end-to-end manual SELL ladder call
--           graph... manual_execution_request absent").
-- Non-goals: no FK from execution_sell_reservation.manual_execution_request_id
--            to this table yet (atomic reservation creation is a separate,
--            not-yet-implemented step — see review §13 items 4/9) · no
--            provenance_id FK to execution_research_provenance yet (binding
--            provenance to a request is a separate, not-yet-implemented step
--            — see review §13 item 12) · no ladder-profile/anchor columns
--            (A+ ladder quantity calculation is out of scope here) · no live
--            execution enablement.

CREATE TABLE IF NOT EXISTS manual_execution_request (
    manual_execution_request_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    schema_version            SMALLINT UNSIGNED NOT NULL DEFAULT 1,
    idempotency_key            VARCHAR(128)   NOT NULL,
    created_ts_utc             DATETIME(6)    NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    source                     VARCHAR(64)    NOT NULL COMMENT 'e.g. OPERATOR_CLI, COCKPIT_UI',
    requested_by               VARCHAR(128)   NOT NULL COMMENT 'authenticated user identity',
    mode                       VARCHAR(16)    NOT NULL COMMENT 'PAPER or LIVE; LIVE is rejected by manual_execution_service_v1 before decision_gate',

    trading_account_id         BIGINT UNSIGNED NOT NULL,
    account_code               VARCHAR(64)    NOT NULL,
    venue                      VARCHAR(32)    NOT NULL,
    asset_id                   INT(11)        NOT NULL,
    base_asset                 VARCHAR(32)    NOT NULL,
    quote_asset                VARCHAR(16)    NOT NULL,

    side                       VARCHAR(8)     NOT NULL,

    quantity_policy            VARCHAR(32)    NOT NULL COMMENT 'FULL_AVAILABLE_BASE | FIXED_BASE_QUANTITY | FIXED_QUOTE_NOTIONAL | LADDER_LEVELS',
    requested_base_quantity    DECIMAL(30,12) DEFAULT NULL COMMENT 'user-entered intent only, not an approval; decision_gate resolves the trusted free quantity separately',
    requested_quote_notional   DECIMAL(20,10) DEFAULT NULL,
    ladder_levels_json         TEXT           DEFAULT NULL COMMENT 'raw user-entered [[price, fraction], ...] request; not venue-rounded or approved',

    provenance_id              BIGINT UNSIGNED DEFAULT NULL
        COMMENT 'forward-compatible reference to execution_research_provenance; no FK yet, matching the existing execution_sell_reservation.manual_execution_request_id forward-compat convention — binding provenance is a separate, not-yet-implemented step',

    request_state              VARCHAR(24)    NOT NULL DEFAULT 'DRAFT',
    rejection_code             VARCHAR(64)    DEFAULT NULL,
    rejection_detail           VARCHAR(512)   DEFAULT NULL,
    processed_ts_utc           DATETIME(6)    DEFAULT NULL,

    updated_ts_utc              DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (manual_execution_request_id),
    UNIQUE KEY uq_manual_execution_request_idempotency (idempotency_key),
    KEY idx_manual_execution_request_account_asset_state (trading_account_id, venue, asset_id, request_state),

    CONSTRAINT fk_manual_execution_request_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),

    CONSTRAINT fk_manual_execution_request_asset
        FOREIGN KEY (asset_id) REFERENCES asset (asset_id),

    CONSTRAINT chk_manual_execution_request_mode
        CHECK (mode IN ('PAPER', 'LIVE')),

    CONSTRAINT chk_manual_execution_request_side
        CHECK (side IN ('BUY', 'SELL')),

    CONSTRAINT chk_manual_execution_request_quantity_policy
        CHECK (quantity_policy IN (
            'FULL_AVAILABLE_BASE', 'FIXED_BASE_QUANTITY',
            'FIXED_QUOTE_NOTIONAL', 'LADDER_LEVELS'
        )),

    CONSTRAINT chk_manual_execution_request_state
        CHECK (request_state IN (
            'DRAFT', 'GATE_BLOCKED', 'PLANNED', 'PLAN_REJECTED', 'FAILED'
        ))

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Canonical immutable manual execution request parent. Content fields never change after insert; only request_state/processed_ts_utc/rejection_* advance, and only through src.manual_execution.manual_execution_request_v1.advance_manual_execution_request_state (single hop from DRAFT). A content change must create a new request (new idempotency_key), never mutate an in-flight one.';
