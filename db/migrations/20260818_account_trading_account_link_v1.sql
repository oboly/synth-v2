-- Migration: account_trading_account_link_v1
-- Idempotent: safe to re-run.
-- Purpose: explicit, uniquely-constrained mapping between the legacy
--          account_id identifier space (portfolio_sleeve / execution_plan /
--          portfolio_position / capital_reservation) and the
--          trading_account_id identifier space (account_provisioning,
--          trading_account_credential, execution_ladder_profile,
--          execution_sizing_rule, execution_sell_reservation).
-- Reference: docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
--            finding F6; GitHub Issue #319.
-- Scope: mapping table only (minimal remediation). decision_gate and
--        execution_planner repository call sites that currently accept a
--        bare account_id must resolve/verify it through this table rather
--        than assuming identity with trading_account_id.
-- Out of scope: migrating portfolio_sleeve itself onto trading_account_id
--        (larger effort, explicitly deferred by the source audit/backlog).
-- Data: no rows are seeded by this migration. Seeding the initial
--        account_id -> trading_account_id pairing requires separate,
--        explicitly authorized data entry against the live account_id and
--        trading_account_id values (not verifiable from a migration file).

CREATE TABLE IF NOT EXISTS account_trading_account_link (
    link_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    account_id         INT UNSIGNED    NOT NULL
        COMMENT 'Legacy identifier used by portfolio_sleeve / execution_plan / portfolio_position / capital_reservation',
    trading_account_id BIGINT UNSIGNED NOT NULL,
    created_ts_utc      DATETIME        NOT NULL,
    updated_ts_utc      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (link_id),
    UNIQUE KEY uq_atal_account_id (account_id),
    UNIQUE KEY uq_atal_trading_account_id (trading_account_id),
    CONSTRAINT fk_atal_trading_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Explicit 1:1 mapping from legacy account_id to trading_account_id. See F6 / Issue #319.';
